"""Candidate merging, IoU deduplication, scoring, and global ranking."""

import logging
from typing import List, NamedTuple, Tuple
from app.api.v1.schemas.candidates import (
    CandidateListItem,
    CandidateStatus,
    EditorialGoal,
    GenerationSettings,
    LLMCandidateEvaluation,
    ValidationStatus,
)
from app.domain.candidates.models import RejectedCandidateAudit
from app.domain.candidates.scoring import calculate_overall_score
from app.domain.transcript.models import TranscriptSegment
from app.services.candidates.validation import validate_candidate_against_transcript

logger = logging.getLogger(__name__)


class RankingResult(NamedTuple):
    candidates: List[CandidateListItem]
    rejected_candidates: List[RejectedCandidateAudit]


def compute_temporal_iou(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Calculate Intersection over Union (IoU) of two 1D time intervals.

    Returns:
        IoU value between 0.0 (disjoint) and 1.0 (identical intervals).
    """
    intersection_start = max(start_a, start_b)
    intersection_end = min(end_a, end_b)
    intersection = max(0.0, intersection_end - intersection_start)

    union_start = min(start_a, start_b)
    union_end = max(end_a, end_b)
    union = max(0.0, union_end - union_start)

    if union <= 0.0:
        return 0.0
    return intersection / union


def deduplicate_and_rank_candidates(
    evaluations: List[LLMCandidateEvaluation],
    segments: List[TranscriptSegment],
    editorial_goal: EditorialGoal,
    settings: GenerationSettings,
    source_duration_seconds: float,
    iou_threshold: float = 0.50,
) -> RankingResult:
    """Validate, score, deduplicate, and globally rank candidates from all chunks.

    Deterministic ranking & tie-breaking:
    1. Primary sort: overall_score DESC
    2. Tie-break 1: abs(duration - target_duration) ASC (closer to target duration is preferred)
    3. Tie-break 2: start_seconds ASC (earlier appearance in video)

    Deduplication policy:
    - If IoU >= iou_threshold, suppress the lower-ranked candidate.
    """
    if not evaluations:
        return RankingResult(candidates=[], rejected_candidates=[])

    scored_candidates: List[Tuple[int, float, float, CandidateListItem]] = []
    rejected_records: List[RejectedCandidateAudit] = []
    seen_id = 0

    for eval_item in evaluations:
        validation_res = validate_candidate_against_transcript(
            candidate=eval_item,
            segments=segments,
            settings=settings,
            source_duration_seconds=source_duration_seconds,
        )

        duration = round(eval_item.end_seconds - eval_item.start_seconds, 3)

        if not validation_res.is_valid:
            logger.info(
                f"Dropping rejected candidate [{eval_item.start_seconds:.1f}s - {eval_item.end_seconds:.1f}s] "
                f"(duration={duration:.1f}s, hook='{eval_item.hook[:30]}'): "
                f"{[code.value for code in validation_res.reason_codes]}"
            )
            rejected_records.append(
                RejectedCandidateAudit(
                    start_seconds=eval_item.start_seconds,
                    end_seconds=eval_item.end_seconds,
                    duration_seconds=duration,
                    hook=eval_item.hook,
                    reason_codes=validation_res.reason_codes,
                    reasons=validation_res.reasons,
                )
            )
            continue

        # Calculate backend-owned overall_score
        overall_score = calculate_overall_score(
            breakdown=eval_item.score_dimensions,
            goal=editorial_goal,
            version="v1.0",
        )
        target_diff = abs(duration - settings.target_duration_seconds)

        item = CandidateListItem(
            id=f"cnd_{seen_id:04d}",
            start_seconds=eval_item.start_seconds,
            end_seconds=eval_item.end_seconds,
            duration_seconds=duration,
            hook=eval_item.hook,
            transcript_excerpt=eval_item.transcript_excerpt,
            editorial_goal=editorial_goal,
            overall_score=overall_score,
            score_breakdown=eval_item.score_dimensions,
            rationale=eval_item.rationale,
            evidence=eval_item.evidence,
            confidence_label=eval_item.confidence_label,
            validation_status=validation_res.status,
            selected=False,
            status=CandidateStatus.SUGGESTED,
            user_edited=False,
        )
        seen_id += 1

        # Tuple for sorting: (-overall_score, target_diff, start_seconds, item)
        scored_candidates.append((overall_score, target_diff, item.start_seconds, item))

    # Sort candidates by ranking hierarchy
    scored_candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

    # Deduplicate using greedy Non-Maximum Suppression (NMS) on temporal IoU
    surviving_candidates: List[CandidateListItem] = []

    for score, target_diff, start_sec, candidate in scored_candidates:
        is_duplicate = False
        replace_index = -1
        for idx, accepted in enumerate(surviving_candidates):
            iou = compute_temporal_iou(
                candidate.start_seconds,
                candidate.end_seconds,
                accepted.start_seconds,
                accepted.end_seconds,
            )
            # Standard IoU check: if IoU >= threshold, candidate overlaps substantially with an accepted window
            if iou >= iou_threshold:
                endpoint_diff = abs(candidate.end_seconds - accepted.end_seconds)
                # If the current candidate is a significantly longer completion (>6s) of an accepted truncated window,
                # retain it as a distinct resolution option
                if endpoint_diff > 6.0 and candidate.end_seconds > accepted.end_seconds:
                    logger.debug(
                        f"Retaining candidate [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] despite IoU={iou:.2f} "
                        f"because endpoint differs by {endpoint_diff:.1f}s providing distinct resolution over [{accepted.start_seconds:.1f}s - {accepted.end_seconds:.1f}s]."
                    )
                # Conversely, if an already accepted candidate was longer and complete, a shorter candidate is redundant
                else:
                    logger.debug(
                        f"Suppressing duplicate candidate [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] "
                        f"(score={candidate.overall_score}) due to IoU={iou:.2f} with accepted [{accepted.start_seconds:.1f}s - {accepted.end_seconds:.1f}s] (score={accepted.overall_score})"
                    )
                    is_duplicate = True
                    break

        if not is_duplicate:
            # Overlap check: If candidate completely subsumes or is subsumed by an accepted candidate,
            # ensure we don't suppress a candidate with a significantly different, more complete endpoint
            surviving_candidates.append(candidate)

        # Stop if we hit display_limit
        if len(surviving_candidates) >= settings.display_limit:
            break

    # Re-assign clean IDs after final ranking
    for idx, c in enumerate(surviving_candidates, 1):
        c.id = f"cnd_{idx:03d}"

    logger.info(
        f"Ranked {len(surviving_candidates)} final candidate moments across source "
        f"(display_limit={settings.display_limit}, iou_threshold={iou_threshold})"
    )
    return RankingResult(candidates=surviving_candidates, rejected_candidates=rejected_records)
