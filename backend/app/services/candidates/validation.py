"""Candidate validation service: grounds candidates against source media and transcript."""

import logging
import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from pydantic import BaseModel, Field

from app.domain.candidates.models import (
    EvidenceItem,
    GenerationSettings,
    LLMCandidateEvaluation,
    ValidationReasonCode,
    ValidationStatus,
)
from app.domain.transcript.models import TranscriptSegment, WordTiming

logger = logging.getLogger(__name__)


class CandidateValidationResult(NamedTuple):
    is_valid: bool
    status: ValidationStatus
    reasons: List[str]
    reason_codes: List[ValidationReasonCode]


HARD_REJECTION_CODES = {
    ValidationReasonCode.START_NEGATIVE,
    ValidationReasonCode.END_EXCEEDS_SOURCE,
    ValidationReasonCode.DURATION_NON_POSITIVE,
    ValidationReasonCode.DURATION_BELOW_MINIMUM,
    ValidationReasonCode.DURATION_EXCEEDS_MAXIMUM,
    ValidationReasonCode.NO_EVIDENCE,
    ValidationReasonCode.EVIDENCE_NOT_GROUNDED,
    ValidationReasonCode.EVIDENCE_OUTSIDE_WINDOW,
    ValidationReasonCode.UNRESOLVED_CONVERSATIONAL_QUESTION,
}


def _normalize_text_for_matching(text: str) -> str:
    """Strip punctuation and lowercase text for robust substring matching."""
    cleaned = re.sub(r"[-—–/]", " ", text)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.lower().split())


def align_text_to_segments(
    text: str,
    segments: List[TranscriptSegment],
    min_overlap_ratio: float = 0.60,
    max_segment_span: int = 35,
) -> Optional[Tuple[float, float, int, int]]:
    """Align verbatim text (such as excerpt or quote) against transcript segments.
    
    Returns:
        (start_seconds, end_seconds, start_seg_idx, end_seg_idx) if aligned, else None.
    """
    norm_text = _normalize_text_for_matching(text)
    words = norm_text.split()
    if not words:
        return None

    n = len(segments)
    seg_texts = [_normalize_text_for_matching(s.text) for s in segments]

    # Strategy 1: Exact substring across contiguous segments (1 to max_segment_span)
    for window_len in range(1, min(max_segment_span + 1, n + 1)):
        for i in range(n - window_len + 1):
            window_str = " ".join(seg_texts[i : i + window_len])
            if norm_text in window_str:
                return (
                    segments[i].start_seconds,
                    segments[i + window_len - 1].end_seconds,
                    i,
                    i + window_len - 1,
                )

    # Strategy 2: Start and end anchor phrases (for longer excerpts)
    start_phrase = " ".join(words[: min(4, len(words))])
    end_phrase = " ".join(words[-min(4, len(words)) :])

    start_indices = [i for i, st in enumerate(seg_texts) if start_phrase in st]
    end_indices = [i for i, st in enumerate(seg_texts) if end_phrase in st]

    best_match = None
    best_score = 0.0

    for s_idx in start_indices:
        for e_idx in end_indices:
            if s_idx <= e_idx and (e_idx - s_idx) <= max_segment_span:
                span_words = " ".join(seg_texts[s_idx : e_idx + 1]).split()
                w_set = set(span_words)
                matched = sum(1 for w in words if w in w_set)
                score = matched / len(words)
                if score > best_score:
                    best_score = score
                    best_match = (
                        segments[s_idx].start_seconds,
                        segments[e_idx].end_seconds,
                        s_idx,
                        e_idx,
                    )

    if best_score >= min_overlap_ratio and best_match is not None:
        return best_match

    # Strategy 3: Sliding window word overlap
    words_set = set(words)
    for window_len in range(1, min(max_segment_span + 1, n + 1)):
        for i in range(n - window_len + 1):
            window_words = set(" ".join(seg_texts[i : i + window_len]).split())
            matched = len(words_set.intersection(window_words))
            score = matched / len(words_set)
            if score > best_score:
                best_score = score
                best_match = (
                    segments[i].start_seconds,
                    segments[i + window_len - 1].end_seconds,
                    i,
                    i + window_len - 1,
                )

    if best_score >= min_overlap_ratio and best_match is not None:
        return best_match

    return None


def _find_quote_spans_in_segments(
    norm_quote: str,
    quote_words: List[str],
    segments: List[TranscriptSegment],
    candidate_interval: Optional[Tuple[float, float]] = None,
) -> List[Tuple[float, float]]:
    """Locate matching start/end timestamp spans of a quote across transcript segments and words.

    Returns:
        List of (start_seconds, end_seconds) tuples for each occurrence.
    """
    matches: List[Tuple[float, float]] = []
    n = len(segments)

    # 1. Search for exact substring match across consecutive segment spans (from 1 to 25 segments)
    for span_len in range(1, min(25, n + 1)):
        for i in range(n - span_len + 1):
            span_segs = segments[i : i + span_len]
            span_text = " ".join(s.text for s in span_segs)
            norm_span = _normalize_text_for_matching(span_text)

            if norm_quote in norm_span:
                start_sec = span_segs[0].start_seconds
                end_sec = span_segs[-1].end_seconds

                # Refine to exact word boundaries if word timings are available
                words_in_span: List[WordTiming] = []
                for s in span_segs:
                    if s.words:
                        words_in_span.extend(s.words)

                if words_in_span:
                    norm_words = [_normalize_text_for_matching(w.word) for w in words_in_span]
                    qw_len = len(quote_words)
                    for k in range(len(norm_words) - qw_len + 1):
                        if norm_words[k : k + qw_len] == quote_words:
                            start_sec = words_in_span[k].start_seconds
                            end_sec = words_in_span[k + qw_len - 1].end_seconds
                            break
                elif span_len == 1 and norm_span:
                    span_words = norm_span.split()
                    qw_len = len(quote_words)
                    for k in range(len(span_words) - qw_len + 1):
                        if span_words[k : k + qw_len] == quote_words:
                            total_words = len(span_words)
                            dur = end_sec - start_sec
                            est_start = start_sec + (k / total_words) * dur
                            est_end = start_sec + ((k + qw_len) / total_words) * dur
                            start_sec = round(est_start, 2)
                            end_sec = round(est_end, 2)
                            break

                matches.append((start_sec, end_sec))
        if matches:
            break

    # 2. Fallback: align_text_to_segments
    if not matches:
        aligned = align_text_to_segments(norm_quote, segments, min_overlap_ratio=0.70)
        if aligned:
            matches.append((aligned[0], aligned[1]))

    if matches and candidate_interval:
        c_start, c_end = candidate_interval
        # Score matches by temporal proximity to [c_start, c_end]
        def match_distance(m: Tuple[float, float]) -> float:
            m_start, m_end = m
            # Overlap has distance 0.0
            overlap = min(m_end, c_end) - max(m_start, c_start)
            if overlap > 0:
                return -overlap
            # Disjoint distance
            if m_end < c_start:
                return c_start - m_end
            return m_start - c_end
        matches.sort(key=match_distance)

    return matches


class EvidenceReconciliationResult(BaseModel):
    """Audit record for candidate evidence-to-timestamp reconciliation and bounded repair."""
    is_valid: bool
    is_repaired: bool
    original_start_seconds: float
    original_end_seconds: float
    repaired_start_seconds: float
    repaired_end_seconds: float
    evidence_start_seconds: Optional[float] = None
    evidence_end_seconds: Optional[float] = None
    reason: str
    reason_code: Optional[ValidationReasonCode] = None


def reconcile_candidate_evidence_timestamps(
    candidate: LLMCandidateEvaluation,
    segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
    tolerance_seconds: float = 5.0,
) -> EvidenceReconciliationResult:
    """Validate that candidate evidence is temporally covered by the candidate window.
    
    If evidence or excerpt clearly extends outside proposed window, attempts a bounded
    timestamp repair if the evidence can be reliably bounded within max_duration_seconds.
    Otherwise flags and rejects with EVIDENCE_OUTSIDE_WINDOW.
    """
    orig_start = candidate.start_seconds
    orig_end = candidate.end_seconds

    # 1. Locate all evidence quote spans
    evidence_spans: List[Tuple[float, float]] = []
    if candidate.evidence:
        for ev in candidate.evidence:
            norm_q = _normalize_text_for_matching(ev.quote)
            if not norm_q:
                continue
            spans = _find_quote_spans_in_segments(norm_q, norm_q.split(), segments, candidate_interval=(orig_start, orig_end))
            if spans:
                evidence_spans.append(spans[0])

    # 2. Locate transcript_excerpt span if provided
    excerpt_span = None
    if candidate.transcript_excerpt:
        excerpt_span = align_text_to_segments(candidate.transcript_excerpt, segments)

    # If neither evidence quotes nor excerpt could be grounded
    if not evidence_spans and excerpt_span is None:
        return EvidenceReconciliationResult(
            is_valid=False,
            is_repaired=False,
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            repaired_start_seconds=orig_start,
            repaired_end_seconds=orig_end,
            reason="No candidate evidence quotes or transcript excerpt could be grounded in transcript.",
            reason_code=ValidationReasonCode.EVIDENCE_NOT_GROUNDED,
        )

    all_starts = [s[0] for s in evidence_spans]
    all_ends = [s[1] for s in evidence_spans]
    if excerpt_span:
        all_starts.append(excerpt_span[0])
        all_ends.append(excerpt_span[1])

    ev_min_start = min(all_starts)
    ev_max_end = max(all_ends)

    lead_outside = orig_start - ev_min_start
    trail_outside = ev_max_end - orig_end

    # Check if evidence is consistent within tolerance
    if lead_outside <= tolerance_seconds and trail_outside <= tolerance_seconds:
        return EvidenceReconciliationResult(
            is_valid=True,
            is_repaired=False,
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            repaired_start_seconds=orig_start,
            repaired_end_seconds=orig_end,
            evidence_start_seconds=round(ev_min_start, 2),
            evidence_end_seconds=round(ev_max_end, 2),
            reason="Candidate timestamps temporally cover all grounded evidence.",
            reason_code=None,
        )

    # Evidence clearly occurs outside proposed window. Attempt bounded repair.
    repaired_start = min(orig_start, ev_min_start) if lead_outside > tolerance_seconds else orig_start
    repaired_end = max(orig_end, ev_max_end) if trail_outside > tolerance_seconds else orig_end

    # Snap repaired boundaries to nearest segment boundaries
    for seg in segments:
        if abs(seg.start_seconds - repaired_start) <= 1.0:
            repaired_start = seg.start_seconds
            break
    for seg in segments:
        if abs(seg.end_seconds - repaired_end) <= 1.0:
            repaired_end = seg.end_seconds
            break

    repaired_duration = round(repaired_end - repaired_start, 3)

    # Boundary and duration invariant checks
    if repaired_end > (source_duration_seconds + 0.1):
        return EvidenceReconciliationResult(
            is_valid=False,
            is_repaired=False,
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            repaired_start_seconds=orig_start,
            repaired_end_seconds=orig_end,
            evidence_start_seconds=round(ev_min_start, 2),
            evidence_end_seconds=round(ev_max_end, 2),
            reason=f"Evidence extends past source duration ({ev_max_end:.1f}s > {source_duration_seconds:.1f}s).",
            reason_code=ValidationReasonCode.END_EXCEEDS_SOURCE,
        )

    if repaired_duration > settings.max_duration_seconds:
        return EvidenceReconciliationResult(
            is_valid=False,
            is_repaired=False,
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            repaired_start_seconds=orig_start,
            repaired_end_seconds=orig_end,
            evidence_start_seconds=round(ev_min_start, 2),
            evidence_end_seconds=round(ev_max_end, 2),
            reason=(
                f"Candidate narrative evidence spans {repaired_duration:.1f}s "
                f"([{repaired_start:.1f}s - {repaired_end:.1f}s]), which exceeds maximum "
                f"clip duration ({settings.max_duration_seconds:.1f}s)."
            ),
            reason_code=ValidationReasonCode.EVIDENCE_OUTSIDE_WINDOW,
        )

    # Bounded repair successful
    reasons = []
    if lead_outside > tolerance_seconds:
        reasons.append(f"Extended start from {orig_start:.2f}s to {repaired_start:.2f}s to cover earlier evidence at {ev_min_start:.2f}s")
    if trail_outside > tolerance_seconds:
        reasons.append(f"Extended end from {orig_end:.2f}s to {repaired_end:.2f}s to cover described evidence/story climax at {ev_max_end:.2f}s")

    return EvidenceReconciliationResult(
        is_valid=True,
        is_repaired=True,
        original_start_seconds=orig_start,
        original_end_seconds=orig_end,
        repaired_start_seconds=round(repaired_start, 3),
        repaired_end_seconds=round(repaired_end, 3),
        evidence_start_seconds=round(ev_min_start, 2),
        evidence_end_seconds=round(ev_max_end, 2),
        reason="; ".join(reasons),
        reason_code=None,
    )


# Common rhetorical/comedic question patterns that are self-contained closures
RHETORICAL_CLOSURE_PATTERNS = [
    r"\bare you kidding me\b",
    r"\bare you serious\b",
    r"\bwho doesnt love\b",
    r"\bwhat was i thinking\b",
    r"\bcan you believe it\b",
    r"\bcan you believe that\b",
    r"\bcome on\b",
    r"\bhow about that\b",
    r"\bwhat do you know\b",
    r"\bdid you see the raccoons\b",
]

QUESTION_PATTERNS = [
    r"\b(do you|did you|have you|would you|could you|what is|what was|what do|why did|why do|is there|are you|how do|how did)\b",
]


class ConversationalClosureResult(BaseModel):
    """Result of short conversational turn closure analysis."""
    is_resolved: bool
    is_expanded: bool
    original_end_seconds: float
    closed_end_seconds: float
    ends_with_question: bool
    is_rhetorical: bool
    reason: str
    reason_code: Optional[ValidationReasonCode] = None


def check_and_resolve_conversational_closure(
    start_seconds: float,
    end_seconds: float,
    segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
) -> ConversationalClosureResult:
    """Inspect the end of a short candidate to ensure conversational questions are resolved.
    
    If the candidate ends on an unresolved question, expands to include the subsequent
    speaker's answer or reaction if within max_duration_seconds. If it cannot fit,
    flags as unresolved.
    """
    orig_end = float(end_seconds)

    # Find the last segment covered by the candidate window
    end_seg_idx = None
    for idx, seg in enumerate(segments):
        if seg.start_seconds < orig_end - 0.05:
            end_seg_idx = idx
        else:
            break

    if end_seg_idx is None:
        # Candidate end is outside segments or between segments
        return ConversationalClosureResult(
            is_resolved=True,
            is_expanded=False,
            original_end_seconds=orig_end,
            closed_end_seconds=orig_end,
            ends_with_question=False,
            is_rhetorical=False,
            reason="Candidate end does not align with segment boundary.",
        )

    end_seg = segments[end_seg_idx]
    norm_end_text = _normalize_text_for_matching(end_seg.text)

    # Check if ends with question mark or question pattern
    has_q_mark = end_seg.text.strip().endswith(("?", "?!", "!?")) or "?" in end_seg.text.strip()[-3:]
    has_q_pattern = any(re.search(pat, norm_end_text) for pat in QUESTION_PATTERNS)
    is_question = has_q_mark or has_q_pattern

    if not is_question:
        return ConversationalClosureResult(
            is_resolved=True,
            is_expanded=False,
            original_end_seconds=orig_end,
            closed_end_seconds=orig_end,
            ends_with_question=False,
            is_rhetorical=False,
            reason="Candidate does not end on a question.",
        )

    # Check if rhetorical or comedic tagline
    is_rhetorical = any(re.search(pat, norm_end_text) for pat in RHETORICAL_CLOSURE_PATTERNS)
    if is_rhetorical:
        return ConversationalClosureResult(
            is_resolved=True,
            is_expanded=False,
            original_end_seconds=orig_end,
            closed_end_seconds=orig_end,
            ends_with_question=True,
            is_rhetorical=True,
            reason=f"Candidate ends on a self-contained rhetorical/comedic question: '{end_seg.text}'.",
        )

    # Conversational question detected: look ahead for the answer turn (up to 4 forward segments)
    cur_speaker = end_seg.speaker_label
    answer_end_idx = None

    for forward_idx in range(end_seg_idx + 1, min(len(segments), end_seg_idx + 5)):
        f_seg = segments[forward_idx]
        next_speaker = f_seg.speaker_label
        f_norm = _normalize_text_for_matching(f_seg.text)

        # Stop if crossing topic transition
        if any(re.search(pat, f_norm) for pat in [r"\bwelcome back\b", r"\bour next guest\b", r"\bmoving on\b"]):
            break

        # Check if this segment represents an answer or thought closure (concluding punctuation, backchannel, or response)
        if f_seg.text.strip().endswith((".", "!")) or (cur_speaker and next_speaker and cur_speaker != next_speaker):
            answer_end_idx = forward_idx
            # If the response continues for a full sentence or thought, include it
            if forward_idx + 1 < len(segments):
                f_next = segments[forward_idx + 1]
                # If f_next is the same answering speaker finishing the sentence
                if f_next.speaker_label == next_speaker and not f_seg.text.strip().endswith((".", "!")):
                    answer_end_idx = forward_idx + 1
            break

    if answer_end_idx is not None:
        proposed_end = segments[answer_end_idx].end_seconds
        proposed_duration = round(proposed_end - start_seconds, 3)

        if proposed_duration <= settings.max_duration_seconds and proposed_end <= (source_duration_seconds + 0.1):
            return ConversationalClosureResult(
                is_resolved=True,
                is_expanded=True,
                original_end_seconds=orig_end,
                closed_end_seconds=proposed_end,
                ends_with_question=True,
                is_rhetorical=False,
                reason=f"Expanded short candidate from {orig_end:.2f}s to {proposed_end:.2f}s to include answer turn ('{segments[answer_end_idx].text[:30]}...').",
            )
        else:
            return ConversationalClosureResult(
                is_resolved=False,
                is_expanded=False,
                original_end_seconds=orig_end,
                closed_end_seconds=orig_end,
                ends_with_question=True,
                is_rhetorical=False,
                reason=(
                    f"Candidate ends on unresolved question ('{end_seg.text[:30]}...'), "
                    f"and answer extends duration to {proposed_duration:.1f}s exceeding limit ({settings.max_duration_seconds:.1f}s)."
                ),
                reason_code=ValidationReasonCode.UNRESOLVED_CONVERSATIONAL_QUESTION,
            )

    # No forward answer found within lookahead budget
    return ConversationalClosureResult(
        is_resolved=False,
        is_expanded=False,
        original_end_seconds=orig_end,
        closed_end_seconds=orig_end,
        ends_with_question=True,
        is_rhetorical=False,
        reason=f"Candidate ends on unresolved conversational question with no answer found: '{end_seg.text[:30]}...'",
        reason_code=ValidationReasonCode.UNRESOLVED_CONVERSATIONAL_QUESTION,
    )


def validate_candidate_against_transcript(
    candidate: LLMCandidateEvaluation,
    segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
    quote_tolerance_seconds: float = 5.0,
) -> CandidateValidationResult:
    """Validate a candidate evaluation against source duration, settings, and transcript evidence.

    Returns:
        CandidateValidationResult(is_valid, validation_status, list_of_reasons, list_of_reason_codes)
    """
    reasons: List[str] = []
    reason_codes: List[ValidationReasonCode] = []

    # 1. Bounds check
    if candidate.start_seconds < 0.0:
        reasons.append(f"Candidate start ({candidate.start_seconds}s) is negative.")
        reason_codes.append(ValidationReasonCode.START_NEGATIVE)

    if candidate.end_seconds > source_duration_seconds + 0.1:
        reasons.append(
            f"Candidate end ({candidate.end_seconds}s) exceeds source duration ({source_duration_seconds:.2f}s)."
        )
        reason_codes.append(ValidationReasonCode.END_EXCEEDS_SOURCE)

    duration = round(candidate.end_seconds - candidate.start_seconds, 3)
    if duration <= 0.0:
        reasons.append(f"Candidate duration ({duration}s) is non-positive.")
        reason_codes.append(ValidationReasonCode.DURATION_NON_POSITIVE)
        return CandidateValidationResult(
            is_valid=False,
            status=ValidationStatus.REJECTED,
            reasons=reasons,
            reason_codes=reason_codes,
        )

    # 2. Configured duration limits check
    if duration < settings.min_duration_seconds:
        reasons.append(
            f"Candidate duration ({duration}s) is below minimum ({settings.min_duration_seconds}s)."
        )
        reason_codes.append(ValidationReasonCode.DURATION_BELOW_MINIMUM)

    if duration > settings.max_duration_seconds:
        reasons.append(
            f"Candidate duration ({duration}s) exceeds maximum ({settings.max_duration_seconds}s)."
        )
        reason_codes.append(ValidationReasonCode.DURATION_EXCEEDS_MAXIMUM)

    # 3. Evidence grounding in transcript
    if not candidate.evidence:
        reasons.append("Candidate contains no transcript evidence quotes.")
        reason_codes.append(ValidationReasonCode.NO_EVIDENCE)
    else:
        matched_evidence = 0
        partially_ungrounded = False

        for ev in candidate.evidence:
            norm_quote = _normalize_text_for_matching(ev.quote)
            if not norm_quote:
                continue

            quote_words = norm_quote.split()
            spans = _find_quote_spans_in_segments(norm_quote, quote_words, segments, candidate_interval=(candidate.start_seconds, candidate.end_seconds))

            if not spans:
                partially_ungrounded = True
                reasons.append(
                    f"Evidence quote '{ev.quote[:40]}...' not found in transcript."
                )
                continue

            # Verify temporal alignment
            is_temporally_grounded = False
            for q_start, q_end in spans:
                overlap = min(q_end, candidate.end_seconds) - max(q_start, candidate.start_seconds)
                lead_outside = max(0.0, candidate.start_seconds - q_start)
                trail_outside = max(0.0, q_end - candidate.end_seconds)

                if (
                    overlap > 0
                    and lead_outside <= quote_tolerance_seconds
                    and trail_outside <= quote_tolerance_seconds
                ):
                    is_temporally_grounded = True
                    break

            if is_temporally_grounded:
                matched_evidence += 1
            else:
                partially_ungrounded = True
                reasons.append(
                    f"Evidence quote '{ev.quote[:40]}...' at [{spans[0][0]:.1f}s - {spans[0][1]:.1f}s] is not contained within candidate interval [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] (tolerance={quote_tolerance_seconds:.1f}s)."
                )

        if matched_evidence == 0 and candidate.evidence:
            reasons.append("None of the candidate evidence quotes could be grounded in the transcript.")
            reason_codes.append(ValidationReasonCode.EVIDENCE_NOT_GROUNDED)
        elif partially_ungrounded:
            reason_codes.append(ValidationReasonCode.EVIDENCE_PARTIALLY_UNGROUNDED)

    # Hard rejection criteria
    is_rejected = any(code in HARD_REJECTION_CODES for code in reason_codes)

    if is_rejected:
        return CandidateValidationResult(
            is_valid=False,
            status=ValidationStatus.REJECTED,
            reasons=reasons,
            reason_codes=reason_codes,
        )
    elif reason_codes:
        return CandidateValidationResult(
            is_valid=True,
            status=ValidationStatus.NEEDS_REVIEW,
            reasons=reasons,
            reason_codes=reason_codes,
        )

    return CandidateValidationResult(
        is_valid=True,
        status=ValidationStatus.VALID,
        reasons=[],
        reason_codes=[],
    )
