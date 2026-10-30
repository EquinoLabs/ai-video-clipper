"""Candidate merging, IoU deduplication, scoring, and global ranking."""

import logging
from typing import List, NamedTuple, Tuple
from app.domain.candidates.models import (
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
from app.services.candidates.validation import (
    validate_candidate_against_transcript,
    reconcile_candidate_evidence_timestamps,
    check_and_resolve_conversational_closure,
)
from app.services.candidates.expansion import expand_long_candidate_to_minimum
from app.domain.candidates.models import ValidationReasonCode

logger = logging.getLogger('app.services.candidates.ranking')


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
    is_long_clip: bool = False,
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
        current_eval = eval_item
        consistency_audit_dict = getattr(current_eval, "consistency_audit", None)
        expansion_audit_dict = getattr(current_eval, "expansion_audit", None)

        if is_long_clip:
            # 1. Evidence-to-timestamp consistency validation & bounded repair (Phase 2, P0)
            recon_res = reconcile_candidate_evidence_timestamps(
                candidate=current_eval,
                segments=segments,
                settings=settings,
                source_duration_seconds=source_duration_seconds,
            )
            if not recon_res.is_valid:
                reason_code = recon_res.reason_code or ValidationReasonCode.EVIDENCE_OUTSIDE_WINDOW
                logger.info(
                    f"Dropping candidate failing evidence consistency [{current_eval.start_seconds:.1f}s - {current_eval.end_seconds:.1f}s]: {recon_res.reason}"
                )
                rejected_records.append(
                    RejectedCandidateAudit(
                        start_seconds=current_eval.start_seconds,
                        end_seconds=current_eval.end_seconds,
                        duration_seconds=round(current_eval.end_seconds - current_eval.start_seconds, 3),
                        hook=current_eval.hook,
                        reason_codes=[reason_code],
                        reasons=[recon_res.reason],
                    )
                )
                continue

            if recon_res.is_repaired:
                consistency_audit_dict = recon_res.model_dump()
                current_eval = current_eval.model_copy(
                    update={
                        "start_seconds": recon_res.repaired_start_seconds,
                        "end_seconds": recon_res.repaired_end_seconds,
                        "consistency_audit": consistency_audit_dict,
                    }
                )

            # 2. Controlled Long-Boundary Expansion (Phase 3, P0)
            cur_dur = round(current_eval.end_seconds - current_eval.start_seconds, 3)
            if cur_dur < settings.min_duration_seconds:
                exp_res = expand_long_candidate_to_minimum(
                    start_seconds=current_eval.start_seconds,
                    end_seconds=current_eval.end_seconds,
                    segments=segments,
                    settings=settings,
                    source_duration_seconds=source_duration_seconds,
                )
                if exp_res.success and exp_res.expanded:
                    expansion_audit_dict = exp_res.model_dump()
                    current_eval = current_eval.model_copy(
                        update={
                            "start_seconds": exp_res.expanded_start_seconds,
                            "end_seconds": exp_res.expanded_end_seconds,
                            "expansion_audit": expansion_audit_dict,
                        }
                    )
        else:
            # Short-clip conversational turn closure check (Phase 4, P1)
            closure_res = check_and_resolve_conversational_closure(
                start_seconds=current_eval.start_seconds,
                end_seconds=current_eval.end_seconds,
                segments=segments,
                settings=settings,
                source_duration_seconds=source_duration_seconds,
            )
            if not closure_res.is_resolved:
                logger.info(
                    f"Dropping short candidate failing conversational closure [{current_eval.start_seconds:.1f}s - {current_eval.end_seconds:.1f}s]: {closure_res.reason}"
                )
                rejected_records.append(
                    RejectedCandidateAudit(
                        start_seconds=current_eval.start_seconds,
                        end_seconds=current_eval.end_seconds,
                        duration_seconds=round(current_eval.end_seconds - current_eval.start_seconds, 3),
                        hook=current_eval.hook,
                        reason_codes=[closure_res.reason_code or ValidationReasonCode.UNRESOLVED_CONVERSATIONAL_QUESTION],
                        reasons=[closure_res.reason],
                    )
                )
                continue
            elif closure_res.is_expanded:
                current_eval = current_eval.model_copy(
                    update={
                        "end_seconds": closure_res.closed_end_seconds,
                    }
                )

        # 3. Grounding and duration validation against transcript
        validation_res = validate_candidate_against_transcript(
            candidate=current_eval,
            segments=segments,
            settings=settings,
            source_duration_seconds=source_duration_seconds,
        )

        duration = round(current_eval.end_seconds - current_eval.start_seconds, 3)

        if not validation_res.is_valid:
            logger.info(
                f"Dropping rejected candidate [{current_eval.start_seconds:.1f}s - {current_eval.end_seconds:.1f}s] "
                f"(duration={duration:.1f}s, hook='{current_eval.hook[:30]}'): "
                f"{[code.value for code in validation_res.reason_codes]}"
            )
            rejected_records.append(
                RejectedCandidateAudit(
                    start_seconds=current_eval.start_seconds,
                    end_seconds=current_eval.end_seconds,
                    duration_seconds=duration,
                    hook=current_eval.hook,
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
            start_seconds=current_eval.start_seconds,
            end_seconds=current_eval.end_seconds,
            duration_seconds=duration,
            hook=current_eval.hook,
            transcript_excerpt=current_eval.transcript_excerpt,
            editorial_goal=editorial_goal,
            overall_score=overall_score,
            score_breakdown=current_eval.score_dimensions,
            rationale=current_eval.rationale,
            evidence=current_eval.evidence,
            confidence_label=current_eval.confidence_label,
            validation_status=validation_res.status,
            selected=False,
            status=CandidateStatus.SUGGESTED,
            user_edited=False,
            consistency_audit=consistency_audit_dict,
            expansion_audit=expansion_audit_dict,
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
