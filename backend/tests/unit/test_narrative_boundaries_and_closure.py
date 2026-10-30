"""Comprehensive unit tests for narrative boundary consistency, long boundary expansion, and short conversational closure."""

import pytest
from typing import List

from app.domain.candidates.models import (
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    LLMCandidateEvaluation,
    ScoreBreakdown,
    ValidationReasonCode,
    ValidationStatus,
)
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.candidates.expansion import expand_long_candidate_to_minimum, LongExpansionAudit
from app.services.candidates.ranking import deduplicate_and_rank_candidates
from app.services.candidates.validation import (
    align_text_to_segments,
    check_and_resolve_conversational_closure,
    reconcile_candidate_evidence_timestamps,
    validate_candidate_against_transcript,
)


@pytest.fixture
def sample_segments() -> List[TranscriptSegment]:
    """Realistic transcript segments containing questions, answers, and topic transitions."""
    return [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0, text="Welcome to the show everybody.", speaker_label="host"),
        TranscriptSegment(id=1, start_seconds=10.0, end_seconds=15.0, duration_seconds=5.0, text="Thank you for being here.", speaker_label="host"),
        # Moment A style: competitive games
        TranscriptSegment(id=2, start_seconds=15.0, end_seconds=20.0, duration_seconds=5.0, text="Are you competitive when you play games at home?", speaker_label="host"),
        TranscriptSegment(id=3, start_seconds=20.0, end_seconds=25.0, duration_seconds=5.0, text="I do not mean to be, but then points are on.", speaker_label="guest"),
        TranscriptSegment(id=4, start_seconds=25.0, end_seconds=30.0, duration_seconds=5.0, text="Something takes over and I want to win.", speaker_label="guest"),
        TranscriptSegment(id=5, start_seconds=30.0, end_seconds=35.0, duration_seconds=5.0, text="I am less competitive now because of kids.", speaker_label="guest"),
        TranscriptSegment(id=6, start_seconds=35.0, end_seconds=42.0, duration_seconds=7.0, text="Motherhood softened me, but my daughter plays for money.", speaker_label="guest"),
        TranscriptSegment(id=7, start_seconds=42.0, end_seconds=46.0, duration_seconds=4.0, text="That is hilarious. Play for money!", speaker_label="host"),
        # Topic transition
        TranscriptSegment(id=8, start_seconds=48.0, end_seconds=55.0, duration_seconds=7.0, text="Moving on, let's talk about the movie trivia game.", speaker_label="host"),
        TranscriptSegment(id=9, start_seconds=55.0, end_seconds=65.0, duration_seconds=10.0, text="Have you seen one of those trivia games with cards?", speaker_label="host"),
        TranscriptSegment(id=10, start_seconds=65.0, end_seconds=75.0, duration_seconds=10.0, text="I was on a streak where I could not miss any movie questions.", speaker_label="guest"),
        TranscriptSegment(id=11, start_seconds=75.0, end_seconds=85.0, duration_seconds=10.0, text="Then they asked about junior executive and I said Emily Blunt.", speaker_label="guest"),
        TranscriptSegment(id=12, start_seconds=85.0, end_seconds=92.0, duration_seconds=7.0, text="And it was actually me. I was genuinely confused.", speaker_label="guest"),
        TranscriptSegment(id=13, start_seconds=92.0, end_seconds=95.0, duration_seconds=3.0, text="That is wild. You forgot your own role!", speaker_label="host"),
        # Short question-answer exchange
        TranscriptSegment(id=14, start_seconds=98.0, end_seconds=104.0, duration_seconds=6.0, text="Do you get nervous doing outdoor theater?", speaker_label="host"),
        TranscriptSegment(id=15, start_seconds=104.0, end_seconds=112.0, duration_seconds=8.0, text="Nothing went wrong, but it rained almost every night.", speaker_label="guest"),
        TranscriptSegment(id=16, start_seconds=112.0, end_seconds=116.0, duration_seconds=4.0, text="Are you kidding me?!", speaker_label="host"),  # rhetorical question
        TranscriptSegment(id=17, start_seconds=116.0, end_seconds=120.0, duration_seconds=4.0, text="Rained every single night.", speaker_label="guest"),
    ]


@pytest.fixture
def long_settings() -> GenerationSettings:
    return GenerationSettings.for_long_clips(
        min_duration_seconds=30.0,
        preferred_min_seconds=45.0,
        preferred_max_seconds=120.0,
        target_duration_seconds=90.0,
        max_duration_seconds=180.0,
    )


@pytest.fixture
def short_settings() -> GenerationSettings:
    return GenerationSettings.for_short_clips(
        min_duration_seconds=10.0,
        preferred_min_seconds=15.0,
        preferred_max_seconds=45.0,
        target_duration_seconds=30.0,
        max_duration_seconds=60.0,
    )


def test_align_text_to_segments_handles_punctuation_and_spans(sample_segments):
    """Align text across segment boundaries despite punctuation or formatting differences."""
    query = "Are you competitive when you play games at home? I do not mean to be, but then points are on."
    aligned = align_text_to_segments(query, sample_segments)
    assert aligned is not None
    start_sec, end_sec, s_idx, e_idx = aligned
    assert start_sec == 15.0
    assert end_sec == 25.0
    assert s_idx == 2
    assert e_idx == 3


def test_align_text_to_segments_unreliable_returns_none(sample_segments):
    """Text not in transcript should return None without guessing."""
    query = "Completely hallucinated dialogue about rocket ships on Mars."
    aligned = align_text_to_segments(query, sample_segments)
    assert aligned is None


def test_reconcile_evidence_fully_inside_window(sample_segments, long_settings):
    """Candidate timestamps already cover the evidence."""
    cand = LLMCandidateEvaluation(
        start_seconds=15.0,
        end_seconds=46.0,
        hook="Competitive games discussion",
        transcript_excerpt="Are you competitive when you play games at home? Motherhood softened me.",
        score_dimensions=ScoreBreakdown(hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0, goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0, pacing_conciseness=4.0, ending_quality=4.0),
        rationale="Solid games talk",
        evidence=[
            EvidenceItem(start_seconds=20.0, end_seconds=25.0, quote="points are on"),
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = reconcile_candidate_evidence_timestamps(cand, sample_segments, long_settings, 150.0)
    assert res.is_valid is True
    assert res.is_repaired is False
    assert res.repaired_start_seconds == 15.0
    assert res.repaired_end_seconds == 46.0


def test_reconcile_evidence_extending_beyond_end(sample_segments, long_settings):
    """Raccoon-case: excerpt extends past candidate end_seconds; system repairs end."""
    cand = LLMCandidateEvaluation(
        start_seconds=55.0,
        end_seconds=75.0,  # ends at 75.0s, but excerpt and evidence reach to 95.0s
        hook="Movie trivia confusion",
        transcript_excerpt="Have you seen one of those trivia games with cards? ... That is wild. You forgot your own role!",
        score_dimensions=ScoreBreakdown(hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0, goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0, pacing_conciseness=4.0, ending_quality=4.0),
        rationale="Forgot own role",
        evidence=[
            EvidenceItem(start_seconds=65.0, end_seconds=75.0, quote="streak where I could not miss"),
            EvidenceItem(start_seconds=85.0, end_seconds=92.0, quote="And it was actually me"),
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = reconcile_candidate_evidence_timestamps(cand, sample_segments, long_settings, 150.0)
    assert res.is_valid is True
    assert res.is_repaired is True
    assert res.repaired_end_seconds >= 92.0
    assert "Extended end" in res.reason


def test_reconcile_evidence_occurring_before_start(sample_segments, long_settings):
    """Moment A-case: candidate starts late, but cites earlier evidence."""
    cand = LLMCandidateEvaluation(
        start_seconds=30.0,  # starts at 30.0s
        end_seconds=46.0,
        hook="Parenting and games",
        transcript_excerpt="I am less competitive now because of kids.",
        score_dimensions=ScoreBreakdown(hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0, goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0, pacing_conciseness=4.0, ending_quality=4.0),
        rationale="Competitive parenting",
        evidence=[
            EvidenceItem(start_seconds=15.0, end_seconds=20.0, quote="Are you competitive when you play games at home?"),
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = reconcile_candidate_evidence_timestamps(cand, sample_segments, long_settings, 150.0)
    assert res.is_valid is True
    assert res.is_repaired is True
    assert res.repaired_start_seconds <= 15.0
    assert "Extended start" in res.reason


def test_reconcile_evidence_exceeding_max_duration_rejected(sample_segments):
    """When described story evidence spans wider than max_duration_seconds, reject rather than guess."""
    tiny_settings = GenerationSettings(
        min_duration_seconds=5.0,
        preferred_min_seconds=10.0,
        preferred_max_seconds=15.0,
        target_duration_seconds=12.0,
        max_duration_seconds=20.0,
        candidate_pool_target=10,
        display_limit=10,
    )
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=20.0,
        hook="Long story",
        transcript_excerpt="Thank you for being here... Motherhood softened me, but my daughter plays for money.",
        score_dimensions=ScoreBreakdown(hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0, goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0, pacing_conciseness=4.0, ending_quality=4.0),
        rationale="Spans 35 seconds",
        evidence=[
            EvidenceItem(start_seconds=10.0, end_seconds=15.0, quote="Thank you for being here."),
            EvidenceItem(start_seconds=35.0, end_seconds=42.0, quote="Motherhood softened me"),
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = reconcile_candidate_evidence_timestamps(cand, sample_segments, tiny_settings, 150.0)
    assert res.is_valid is False
    assert res.reason_code == ValidationReasonCode.EVIDENCE_OUTSIDE_WINDOW


def test_long_boundary_expansion_sub_30s_candidate(sample_segments, long_settings):
    """Moment B style: 27s candidate expands coherently across sentence boundaries to satisfy 30s floor."""
    # Segment 10 to 12 is 65.0s to 92.0s -> 27.0s duration (< 30.0s)
    audit: LongExpansionAudit = expand_long_candidate_to_minimum(
        start_seconds=65.0,
        end_seconds=92.0,
        segments=sample_segments,
        settings=long_settings,
        source_duration_seconds=150.0,
    )
    assert audit.success is True
    assert audit.expanded_duration_seconds >= 30.0
    assert audit.expanded_duration_seconds <= long_settings.max_duration_seconds
    assert audit.original_start_seconds == 65.0
    assert audit.original_end_seconds == 92.0


def test_long_boundary_expansion_does_not_cross_topic_transition(sample_segments, long_settings):
    """Expansion must not pull in previous topic across an explicit topic transition."""
    # Segment 9 to 11 is 55.0s to 85.0s (30s). Let's test 55.0s to 75.0s (20s).
    # Segment 8 (48-55s) is "Moving on, let's talk about..."
    # Backward expansion should NOT go before segment 8 into segment 7 (games topic).
    audit = expand_long_candidate_to_minimum(
        start_seconds=55.0,
        end_seconds=75.0,
        segments=sample_segments,
        settings=long_settings,
        source_duration_seconds=150.0,
    )
    assert audit.expanded_start_seconds >= 48.0  # Does not cross before segment 8


def test_long_boundary_expansion_preserves_valid_duration(sample_segments, long_settings):
    """Candidate already >= 30.0s is left unmodified."""
    audit = expand_long_candidate_to_minimum(
        start_seconds=15.0,
        end_seconds=46.0,  # 31.0s
        segments=sample_segments,
        settings=long_settings,
        source_duration_seconds=150.0,
    )
    assert audit.success is True
    assert audit.expanded_start_seconds == 15.0
    assert audit.expanded_end_seconds == 46.0
    assert audit.expanded_duration_seconds == 31.0
    assert audit.expanded_backward_seconds == 0.0
    assert audit.expanded_forward_seconds == 0.0


def test_short_conversational_closure_unresolved_question_expanded(sample_segments, short_settings):
    """Short 1 case: window ending on an unresolved question is expanded to include the answer."""
    # Candidate ends at 104.0s: "Do you get nervous doing outdoor theater?"
    # Answer follows at 104.0s - 112.0s: "Nothing went wrong, but it rained almost every night."
    closure_res = check_and_resolve_conversational_closure(
        start_seconds=98.0,
        end_seconds=104.0,
        segments=sample_segments,
        settings=short_settings,
        source_duration_seconds=150.0,
    )
    assert closure_res.is_resolved is True
    assert closure_res.is_expanded is True
    assert closure_res.closed_end_seconds == 112.0
    assert closure_res.ends_with_question is True
    assert closure_res.is_rhetorical is False


def test_short_conversational_closure_rhetorical_question_intact(sample_segments, short_settings):
    """Comedic / rhetorical exclamation like 'Are you kidding me?!' is kept intact."""
    closure_res = check_and_resolve_conversational_closure(
        start_seconds=104.0,
        end_seconds=116.0,  # Ends with segment 16: "Are you kidding me?!"
        segments=sample_segments,
        settings=short_settings,
        source_duration_seconds=150.0,
    )
    assert closure_res.is_resolved is True
    assert closure_res.is_expanded is False
    assert closure_res.is_rhetorical is True
    assert closure_res.closed_end_seconds == 116.0


def test_short_conversational_closure_exceeding_max_duration_rejected(sample_segments):
    """Unresolved question that cannot fit answer within max_duration is marked unresolved."""
    tight_settings = GenerationSettings(
        min_duration_seconds=5.0,
        preferred_min_seconds=6.0,
        preferred_max_seconds=7.0,
        target_duration_seconds=7.0,
        max_duration_seconds=8.0,
        candidate_pool_target=10,
        display_limit=10,
    )
    # 98.0s to 104.0s is 6.0s. Answer extends to 112.0s (14.0s duration > 8.0s limit).
    closure_res = check_and_resolve_conversational_closure(
        start_seconds=98.0,
        end_seconds=104.0,
        segments=sample_segments,
        settings=tight_settings,
        source_duration_seconds=150.0,
    )
    assert closure_res.is_resolved is False
    assert closure_res.reason_code == ValidationReasonCode.UNRESOLVED_CONVERSATIONAL_QUESTION
