"""Candidate validation service: grounds candidates against source media and transcript."""

import logging
import re
from typing import List, NamedTuple, Optional, Tuple
from app.api.v1.schemas.candidates import (
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
}


def _normalize_text_for_matching(text: str) -> str:
    """Strip punctuation and lowercase text for robust substring matching."""
    cleaned = re.sub(r"[-—–/]", " ", text)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return " ".join(cleaned.lower().split())


def _find_quote_spans_in_segments(
    norm_quote: str,
    quote_words: List[str],
    segments: List[TranscriptSegment],
) -> List[Tuple[float, float]]:
    """Locate matching start/end timestamp spans of a quote across transcript segments and words.

    Returns:
        List of (start_seconds, end_seconds) tuples for each occurrence.
    """
    matches: List[Tuple[float, float]] = []
    n = len(segments)

    # 1. Search for exact substring match across consecutive segment spans (from 1 to 5 segments)
    for span_len in range(1, min(5, n + 1)):
        for i in range(n - span_len + 1):
            span_segs = segments[i:i + span_len]
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
                        if norm_words[k:k + qw_len] == quote_words:
                            start_sec = words_in_span[k].start_seconds
                            end_sec = words_in_span[k + qw_len - 1].end_seconds
                            break
                elif span_len == 1 and norm_span:
                    # When word timings are not attached, interpolate word positions linearly within segment
                    span_words = norm_span.split()
                    qw_len = len(quote_words)
                    for k in range(len(span_words) - qw_len + 1):
                        if span_words[k:k + qw_len] == quote_words:
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

    # 2. Fallback: fuzzy/partial word-level overlap if no exact substring match found
    if not matches and quote_words:
        for span_len in range(1, min(4, n + 1)):
            for i in range(n - span_len + 1):
                span_segs = segments[i:i + span_len]
                span_text = " ".join(s.text for s in span_segs)
                norm_span = _normalize_text_for_matching(span_text)
                span_words = set(norm_span.split())
                words_found = sum(1 for w in quote_words if w in span_words)
                if words_found / len(quote_words) >= 0.70:
                    matches.append((span_segs[0].start_seconds, span_segs[-1].end_seconds))
            if matches:
                break

    return matches


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
            spans = _find_quote_spans_in_segments(norm_quote, quote_words, segments)

            if not spans:
                partially_ungrounded = True
                reasons.append(
                    f"Evidence quote '{ev.quote[:40]}...' not found in transcript."
                )
                continue

            # Verify temporal alignment:
            # The quote must have non-zero temporal overlap with candidate interval,
            # and lead/trail outside the candidate interval must not exceed quote_tolerance_seconds.
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

    # Hard rejection criteria:
    # Any reason code present in HARD_REJECTION_CODES
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
