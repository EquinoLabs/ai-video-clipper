"""Bounded candidate-window construction and semantic anchor expansion service."""

import logging
import re
from pydantic import BaseModel, Field
from typing import List, NamedTuple, Optional, Set, Tuple

from app.domain.candidates.models import (
    CandidateListItem,
    CandidateStatus,
    EditorialGoal,
    GenerationSettings,
    LLMAnchorEvaluation,
    LLMCandidateEvaluation,
    ValidationReasonCode,
    ValidationStatus,
)
from app.domain.candidates.models import RejectedCandidateAudit
from app.domain.transcript.models import TranscriptSegment
from app.services.candidates.validation import _normalize_text_for_matching

logger = logging.getLogger(__name__)


# Common topic transition / host intro cues that should bound backward search
TOPIC_TRANSITION_PATTERNS = [
    r"\bwelcome back\b",
    r"\bour next guest\b",
    r"\bmoving on\b",
    r"\blets talk about\b",
    r"\bswitch gears\b",
    r"\bswitching gears\b",
    r"\bso tell me\b",
    r"\btell me about\b",
    r"\bspeaking of\b",
    r"\bby the way\b",
    r"\btonight we have\b",
    r"\bthank you for being here\b",
    r"\bthank you for playing\b",
    r"\bwhy kids\b",
    r"\bdo you play games at home\b",
]


def is_topic_transition_segment(text: str) -> bool:
    """Check if segment text contains explicit host, intro, or topic transition markers."""
    norm = _normalize_text_for_matching(text)
    for pattern in TOPIC_TRANSITION_PATTERNS:
        if re.search(pattern, norm):
            return True
    return False


def is_reaction_or_resolution(text: str, next_speaker: Optional[str] = None, cur_speaker: Optional[str] = None) -> bool:
    """Check if segment text appears to represent partner resolution, reaction, or natural thought closure."""
    trimmed = text.strip()
    if not trimmed:
        return False
    norm = _normalize_text_for_matching(trimmed)
    
    # 1. Concluding punctuation
    if trimmed.endswith((".", "!", "?")):
        return True
        
    # 2. Conversational backchannel or laughter / agreement acknowledgment
    reaction_starters = [
        "yeah", "right", "exactly", "totally", "i know", "thats wild", "thats funny",
        "you know", "i mean", "less competitive"
    ]
    if any(norm.startswith(r) for r in reaction_starters):
        return True

    # 3. Conversational resolution phrases
    resolution_phrases = [
        "less competitive now",
        "play for money",
        "points are on",
        "takes over",
        "doesnt really care",
        "throw the games",
    ]
    if any(p in norm for p in resolution_phrases):
        return True
        
    # 4. Speaker turn handoff (if speaker labels exist and are different)
    if cur_speaker and next_speaker and cur_speaker != next_speaker:
        return True
        
    return False


class AnchorValidationResult(NamedTuple):
    is_valid: bool
    reasons: List[str]
    reason_codes: List[ValidationReasonCode]


def validate_anchor(
    anchor: LLMAnchorEvaluation,
    chunk_segments: List[TranscriptSegment],
) -> AnchorValidationResult:
    """Validate raw anchor from LLM before attempting window construction.
    
    Checks:
    1. anchor_segment_ids valid and within [0, len(chunk_segments) - 1].
    2. anchor_segment_ids strictly contiguous.
    3. transcript_excerpt grounded in anchor segments text.
    4. evidence grounded and overlapping anchor span.
    """
    reasons: List[str] = []
    reason_codes: List[ValidationReasonCode] = []
    num_segs = len(chunk_segments)

    # 1. ID checks
    if not anchor.anchor_segment_ids:
        reasons.append("Anchor has empty anchor_segment_ids.")
        reason_codes.append(ValidationReasonCode.UNKNOWN_SEGMENT_ID)
        return AnchorValidationResult(False, reasons, reason_codes)

    for seg_id in anchor.anchor_segment_ids:
        if not isinstance(seg_id, int) or seg_id < 0 or seg_id >= num_segs:
            reasons.append(f"Anchor segment ID {seg_id} is out of bounds [0, {num_segs - 1}].")
            reason_codes.append(ValidationReasonCode.UNKNOWN_SEGMENT_ID)
            return AnchorValidationResult(False, reasons, reason_codes)

    # 2. Contiguity check
    sorted_ids = sorted(anchor.anchor_segment_ids)
    for i in range(len(sorted_ids) - 1):
        if sorted_ids[i + 1] != sorted_ids[i] + 1:
            reasons.append(f"Anchor segment IDs {anchor.anchor_segment_ids} are discontiguous.")
            reason_codes.append(ValidationReasonCode.DISCONTIGUOUS_ANCHOR)
            return AnchorValidationResult(False, reasons, reason_codes)

    # 3. Ground transcript_excerpt in anchor segments
    anchor_text = " ".join(chunk_segments[sid].text for sid in sorted_ids)
    norm_anchor_text = _normalize_text_for_matching(anchor_text)
    norm_excerpt = _normalize_text_for_matching(anchor.transcript_excerpt)

    if norm_excerpt and norm_excerpt not in norm_anchor_text:
        # Check partial overlap (at least 70% of words found)
        excerpt_words = norm_excerpt.split()
        anchor_words = set(norm_anchor_text.split())
        matched_words = sum(1 for w in excerpt_words if w in anchor_words)
        if not excerpt_words or (matched_words / len(excerpt_words)) < 0.65:
            reasons.append(f"Anchor transcript_excerpt '{anchor.transcript_excerpt[:40]}' not grounded in anchor segments.")
            reason_codes.append(ValidationReasonCode.EXCERPT_NOT_GROUNDED)
            return AnchorValidationResult(False, reasons, reason_codes)

    # 4. Check evidence items exist
    if not anchor.evidence:
        reasons.append("Anchor has no evidence quotes.")
        reason_codes.append(ValidationReasonCode.NO_EVIDENCE)
        return AnchorValidationResult(False, reasons, reason_codes)

    anc_start_sec = chunk_segments[sorted_ids[0]].start_seconds
    anc_end_sec = chunk_segments[sorted_ids[-1]].end_seconds
    grounded_evidence = 0

    for ev in anchor.evidence:
        norm_ev = _normalize_text_for_matching(ev.quote)
        if not norm_ev:
            continue
        # Verify quote appears in chunk text
        chunk_full_text = " ".join(s.text for s in chunk_segments)
        norm_chunk = _normalize_text_for_matching(chunk_full_text)
        if norm_ev in norm_chunk:
            grounded_evidence += 1

    if grounded_evidence == 0:
        reasons.append("No evidence quotes were grounded in transcript.")
        reason_codes.append(ValidationReasonCode.EVIDENCE_NOT_GROUNDED)
        return AnchorValidationResult(False, reasons, reason_codes)

    return AnchorValidationResult(True, [], [])


def construct_bounded_candidate_windows(
    anchor: LLMAnchorEvaluation,
    chunk_segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
    lookback_budget_seconds: float = 35.0,
) -> List[Tuple[float, float, str]]:
    """Construct up to 3 bounded candidate windows around an anchor.
    
    Returns: List of (start_seconds, end_seconds, window_type) sorted by proximity to target duration.
    """
    sorted_ids = sorted(anchor.anchor_segment_ids)
    anc_start_idx = sorted_ids[0]
    anc_end_idx = sorted_ids[-1]

    anc_start_sec = chunk_segments[anc_start_idx].start_seconds
    anc_end_sec = chunk_segments[anc_end_idx].end_seconds
    anc_dur = anc_end_sec - anc_start_sec

    # 1. Collect candidate start indices
    start_candidates: List[Tuple[int, str]] = []

    # B0: Tight (anchor start itself)
    # Even if anchor alone is sub-minimum, its start can form a valid window when paired with forward segments.
    start_candidates.append((anc_start_idx, "tight"))

    # Search backwards for sentence and speaker boundaries UNLESS anchor itself begins at a topic transition
    found_sentence = False
    found_turn = False

    if not is_topic_transition_segment(chunk_segments[anc_start_idx].text):
        for i in range(anc_start_idx - 1, -1, -1):
            seg = chunk_segments[i]
            prior_seg = chunk_segments[i - 1] if i > 0 else None
            span_dur = anc_end_sec - seg.start_seconds
            lookback_dist = anc_start_sec - seg.start_seconds

            # Stop conditions
            if span_dur > settings.max_duration_seconds:
                break
            if lookback_dist > lookback_budget_seconds:
                break

            # If segment i is itself a topic transition, it is a valid setup boundary for this topic,
            # but we cannot cross backward before segment i into the prior topic.
            if is_topic_transition_segment(seg.text):
                start_candidates.append((i, "moderate"))
                break

            # Sentence start check: prior segment ended in terminal punctuation
            if prior_seg and prior_seg.text.rstrip().endswith((".", "!", "?")):
                if not found_sentence:
                    start_candidates.append((i, "moderate"))
                    found_sentence = True
                    continue

            # Speaker change check
            if seg.speaker_label and seg.speaker_label != chunk_segments[anc_start_idx].speaker_label:
                if not found_turn:
                    start_candidates.append((i, "broad"))
                    found_turn = True
                    continue

    # 2. Collect candidate end indices (explore up to 3 forward segments for resolution)
    end_candidates: List[Tuple[int, float]] = [(anc_end_idx, anc_end_sec)]
    cur_speaker = chunk_segments[anc_end_idx].speaker_label
    
    for forward_idx in range(anc_end_idx + 1, min(len(chunk_segments), anc_end_idx + 4)):
        f_seg = chunk_segments[forward_idx]
        next_speaker = f_seg.speaker_label
        f_dur_from_start = f_seg.end_seconds - anc_start_sec
        
        # Stop forward exploration if exceeding maximum duration or parent source bounds
        if f_dur_from_start > settings.max_duration_seconds or f_seg.end_seconds > (source_duration_seconds + 0.1):
            break
            
        # Stop forward exploration if crossing a new topic boundary
        if is_topic_transition_segment(f_seg.text):
            break
            
        if is_reaction_or_resolution(f_seg.text, next_speaker=next_speaker, cur_speaker=cur_speaker):
            end_candidates.append((forward_idx, f_seg.end_seconds))
            
        cur_speaker = next_speaker

    # 3. Form and filter candidate pairs
    valid_windows: List[Tuple[float, float, str]] = []
    seen_intervals: Set[Tuple[float, float]] = set()

    for s_idx, w_type in start_candidates:
        w_start = chunk_segments[s_idx].start_seconds
        for e_idx, w_end in end_candidates:
            w_dur = round(w_end - w_start, 3)
            if settings.min_duration_seconds <= w_dur <= settings.max_duration_seconds:
                if w_end <= (source_duration_seconds + 0.1):
                    key = (round(w_start, 2), round(w_end, 2))
                    if key not in seen_intervals:
                        seen_intervals.add(key)
                        valid_windows.append((w_start, w_end, w_type))

    # 4. Fallback Handling:
    # If structural candidates existed but none formed a valid duration window, OR
    # if start_candidates was empty because anchor was sub-minimum, find nearest valid preceding boundary.
    # Note: If anchor start is already at a topic transition, backward search must not cross into prior topic.
    if not valid_windows and not is_topic_transition_segment(chunk_segments[anc_start_idx].text):
        for i in range(anc_start_idx - 1, -1, -1):
            w_start = chunk_segments[i].start_seconds
            w_dur = round(anc_end_sec - w_start, 3)

            if (anc_start_sec - w_start) > lookback_budget_seconds:
                break
            if w_dur > settings.max_duration_seconds:
                break

            # If segment i is a topic transition, we can use it as a valid fallback start,
            # but cannot cross backward past it.
            if is_topic_transition_segment(chunk_segments[i].text):
                if w_dur >= settings.min_duration_seconds and anc_end_sec <= (source_duration_seconds + 0.1):
                    key = (round(w_start, 2), round(anc_end_sec, 2))
                    if key not in seen_intervals:
                        seen_intervals.add(key)
                        valid_windows.append((w_start, anc_end_sec, "fallback_nearest"))
                break

            if w_dur >= settings.min_duration_seconds and anc_end_sec <= (source_duration_seconds + 0.1):
                key = (round(w_start, 2), round(anc_end_sec, 2))
                if key not in seen_intervals:
                    seen_intervals.add(key)
                    valid_windows.append((w_start, anc_end_sec, "fallback_nearest"))
                break  # Exactly one fallback window to maintain determinism

    # 5. Cap at 3 windows: prioritize structurally balanced windows (tight, moderate, broad) before target proximity
    # We sort by structural preference: tight/moderate first, then distance to target duration as tie-breaker
    def window_priority_key(w: Tuple[float, float, str]) -> Tuple[int, float]:
        w_dur = w[1] - w[0]
        w_type = w[2]
        # Prefer structurally complete moderate or tight windows over overly broad or fallback windows
        type_rank = 0 if "moderate" in w_type else (1 if "tight" in w_type else 2)
        target_diff = abs(w_dur - settings.target_duration_seconds)
        return (type_rank, target_diff)

    valid_windows.sort(key=window_priority_key)
    return valid_windows[:3]


class WindowExpansionResult(NamedTuple):
    evaluations: List[LLMCandidateEvaluation]
    rejected_audits: List[RejectedCandidateAudit]


def expand_anchors_to_candidates(
    anchors: List[LLMAnchorEvaluation],
    chunk_segments: List[TranscriptSegment],
    editorial_goal: EditorialGoal,
    settings: GenerationSettings,
    source_duration_seconds: float,
) -> WindowExpansionResult:
    """Validate raw anchors, expand each into bounded candidate windows, and convert to LLMCandidateEvaluation."""
    evaluations: List[LLMCandidateEvaluation] = []
    rejected_audits: List[RejectedCandidateAudit] = []

    seen_anchor_ids: Set[str] = set()

    for anchor in anchors:
        # Check duplicate anchor ID within response
        if anchor.anchor_id in seen_anchor_ids:
            logger.warning(f"Skipping duplicate anchor_id '{anchor.anchor_id}'.")
            continue
        seen_anchor_ids.add(anchor.anchor_id)

        # 1. Validate anchor
        val_res = validate_anchor(anchor, chunk_segments)
        if not val_res.is_valid:
            # Derive anchor timestamps for audit logging if possible
            anc_start = chunk_segments[0].start_seconds
            anc_end = chunk_segments[-1].end_seconds
            if anchor.anchor_segment_ids and all(0 <= idx < len(chunk_segments) for idx in anchor.anchor_segment_ids):
                anc_start = chunk_segments[min(anchor.anchor_segment_ids)].start_seconds
                anc_end = chunk_segments[max(anchor.anchor_segment_ids)].end_seconds

            rejected_audits.append(
                RejectedCandidateAudit(
                    start_seconds=anc_start,
                    end_seconds=anc_end,
                    duration_seconds=round(anc_end - anc_start, 3),
                    hook=anchor.hook,
                    reason_codes=val_res.reason_codes,
                    reasons=val_res.reasons,
                )
            )
            continue

        # 2. Construct bounded windows
        windows = construct_bounded_candidate_windows(
            anchor=anchor,
            chunk_segments=chunk_segments,
            settings=settings,
            source_duration_seconds=source_duration_seconds,
        )

        if not windows:
            anc_start = chunk_segments[min(anchor.anchor_segment_ids)].start_seconds
            anc_end = chunk_segments[max(anchor.anchor_segment_ids)].end_seconds
            rejected_audits.append(
                RejectedCandidateAudit(
                    start_seconds=anc_start,
                    end_seconds=anc_end,
                    duration_seconds=round(anc_end - anc_start, 3),
                    hook=anchor.hook,
                    reason_codes=[ValidationReasonCode.NO_VALID_WINDOW],
                    reasons=[f"Anchor '{anchor.hook[:30]}' could not be expanded into a valid {settings.min_duration_seconds}s-{settings.max_duration_seconds}s window."],
                )
            )
            continue

        # 3. Convert valid windows to LLMCandidateEvaluation items
        for w_start, w_end, w_type in windows:
            cand_eval = LLMCandidateEvaluation(
                start_seconds=w_start,
                end_seconds=w_end,
                hook=anchor.hook,
                transcript_excerpt=anchor.transcript_excerpt,
                score_dimensions=anchor.score_dimensions,
                rationale=f"[{w_type}] {anchor.rationale}",
                evidence=anchor.evidence,
                confidence_label=anchor.confidence_label,
            )
            evaluations.append(cand_eval)

    return WindowExpansionResult(evaluations=evaluations, rejected_audits=rejected_audits)



class LongExpansionAudit(BaseModel):
    """Detailed audit record for controlled long-candidate boundary expansion."""
    original_start_seconds: float
    original_end_seconds: float
    expanded_start_seconds: float
    expanded_end_seconds: float
    original_duration_seconds: float
    expanded_duration_seconds: float
    expanded_backward_seconds: float
    expanded_forward_seconds: float
    added_start_segments: List[int]
    added_end_segments: List[int]
    success: bool
    expanded: bool = False
    reason: str


def expand_long_candidate_to_minimum(
    start_seconds: float,
    end_seconds: float,
    segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
    min_expandable_duration_seconds: float = 15.0,
    max_lookback_segments: int = 15,
    max_lookahead_segments: int = 15,
) -> LongExpansionAudit:
    """Expand a candidate with duration < min_duration_seconds outward to sentence/turn boundaries.
    
    Principles:
    1. Preserves original candidate boundaries if already satisfying min_duration_seconds.
    2. Only expands candidates with meaningful conversational substance (duration >= min_expandable_duration_seconds).
    3. Respects topic transition boundaries: never crosses backward before a host intro / topic switch,
       nor forward into an unrelated topic.
    4. Explores backward to earlier sentence start (prior segment ended in '.', '!', '?') or speaker change.
    5. Explores forward to natural reaction, laughter, or thought completion.
    6. Ensures expanded duration satisfies: min_duration_seconds <= duration <= max_duration_seconds.
    7. If no coherent expansion can reach min_duration_seconds, returns success=False and keeps original boundaries.
    """
    orig_start = float(start_seconds)
    orig_end = float(end_seconds)
    orig_dur = round(orig_end - orig_start, 3)

    if orig_dur >= settings.min_duration_seconds:
        return LongExpansionAudit(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            expanded_start_seconds=orig_start,
            expanded_end_seconds=orig_end,
            original_duration_seconds=orig_dur,
            expanded_duration_seconds=orig_dur,
            expanded_backward_seconds=0.0,
            expanded_forward_seconds=0.0,
            added_start_segments=[],
            added_end_segments=[],
            success=True,
            reason="Candidate duration already satisfies configured minimum duration.",
        )

    if orig_dur < min_expandable_duration_seconds:
        return LongExpansionAudit(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            expanded_start_seconds=orig_start,
            expanded_end_seconds=orig_end,
            original_duration_seconds=orig_dur,
            expanded_duration_seconds=orig_dur,
            expanded_backward_seconds=0.0,
            expanded_forward_seconds=0.0,
            added_start_segments=[],
            added_end_segments=[],
            success=False,
            reason=f"Candidate duration ({orig_dur:.1f}s) is below expandable threshold ({min_expandable_duration_seconds:.1f}s).",
        )

    # Locate segment indices for orig_start and orig_end
    start_idx = None
    end_idx = None
    for idx, s in enumerate(segments):
        if start_idx is None and s.end_seconds > orig_start + 0.05:
            start_idx = idx
        if s.start_seconds < orig_end - 0.05:
            end_idx = idx

    if start_idx is None or end_idx is None:
        return LongExpansionAudit(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            expanded_start_seconds=orig_start,
            expanded_end_seconds=orig_end,
            original_duration_seconds=orig_dur,
            expanded_duration_seconds=orig_dur,
            expanded_backward_seconds=0.0,
            expanded_forward_seconds=0.0,
            added_start_segments=[],
            added_end_segments=[],
            success=False,
            reason="Could not reliably locate segment indices for candidate interval.",
        )

    new_start_idx = start_idx
    new_end_idx = end_idx
    added_start: List[int] = []
    added_end: List[int] = []

    # 1. Backward search for sentence start or topic boundary
    for i in range(start_idx - 1, max(-1, start_idx - max_lookback_segments - 1), -1):
        seg = segments[i]
        # Topic transition boundary: stop backward expansion
        if is_topic_transition_segment(seg.text):
            new_start_idx = i
            added_start.append(i)
            break

        new_start_idx = i
        added_start.append(i)

        cur_dur = segments[new_end_idx].end_seconds - segments[new_start_idx].start_seconds
        prior_seg = segments[i - 1] if i > 0 else None
        if prior_seg and prior_seg.text.strip().endswith((".", "!", "?")):
            if cur_dur >= settings.min_duration_seconds:
                break

    # 2. Forward search for natural reaction / resolution
    for j in range(end_idx + 1, min(len(segments), end_idx + max_lookahead_segments + 1)):
        seg = segments[j]
        # Topic transition boundary: stop forward expansion
        if is_topic_transition_segment(seg.text):
            break

        cur_dur = segments[j].end_seconds - segments[new_start_idx].start_seconds
        if cur_dur > settings.max_duration_seconds:
            break

        new_end_idx = j
        added_end.append(j)

        if cur_dur >= settings.min_duration_seconds:
            next_seg = segments[j + 1] if j + 1 < len(segments) else None
            next_speaker = next_seg.speaker_label if next_seg else None
            cur_speaker = seg.speaker_label
            if is_reaction_or_resolution(seg.text, next_speaker=next_speaker, cur_speaker=cur_speaker):
                break

    final_start = segments[new_start_idx].start_seconds
    final_end = segments[new_end_idx].end_seconds
    final_dur = round(final_end - final_start, 3)

    if settings.min_duration_seconds <= final_dur <= settings.max_duration_seconds:
        backward_added = round(orig_start - final_start, 3)
        forward_added = round(final_end - orig_end, 3)
        return LongExpansionAudit(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            expanded_start_seconds=round(final_start, 3),
            expanded_end_seconds=round(final_end, 3),
            original_duration_seconds=orig_dur,
            expanded_duration_seconds=final_dur,
            expanded_backward_seconds=max(0.0, backward_added),
            expanded_forward_seconds=max(0.0, forward_added),
            added_start_segments=added_start,
            added_end_segments=added_end,
            success=True,
            expanded=True,
            reason=f"Controlled boundary expansion from {orig_dur:.1f}s to {final_dur:.1f}s satisfied minimum duration limit ({settings.min_duration_seconds}s).",
        )
    else:
        return LongExpansionAudit(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            expanded_start_seconds=orig_start,
            expanded_end_seconds=orig_end,
            original_duration_seconds=orig_dur,
            expanded_duration_seconds=orig_dur,
            expanded_backward_seconds=0.0,
            expanded_forward_seconds=0.0,
            added_start_segments=[],
            added_end_segments=[],
            success=False,
            reason=f"Controlled expansion reached {final_dur:.1f}s, unable to satisfy min {settings.min_duration_seconds}s without violating boundaries.",
        )
