"""Unit tests for Phase 2 candidate discovery, validation, ranking, and deduplication."""

import json
import logging
from pathlib import Path
import pytest
from app.ai_clipper.domain.candidates.models import (
    CandidateArtifact,
    CandidateGenerationMetadata,
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    LLMCandidateEvaluation,
    RejectedCandidateAudit,
    ScoreBreakdown,
    ValidationReasonCode,
    ValidationStatus,
    write_candidate_artifact,
)
from app.ai_clipper.domain.transcript.models import SourceMediaMetadata, TranscriptSegment, WordTiming
from app.ai_clipper.services.candidates.ranking import (
    RankingResult,
    compute_temporal_iou,
    deduplicate_and_rank_candidates,
)
from app.ai_clipper.services.candidates.validation import (
    CandidateValidationResult,
    validate_candidate_against_transcript,
)
from app.ai_clipper.services.llm.prompts import build_system_prompt


@pytest.fixture
def sample_segments():
    return [
        TranscriptSegment(
            id=0,
            start_seconds=0.0,
            end_seconds=10.0,
            duration_seconds=10.0,
            text="Welcome to the show today we talk about distributed consensus and raft algorithms.",
        ),
        TranscriptSegment(
            id=1,
            start_seconds=10.0,
            end_seconds=30.0,
            duration_seconds=20.0,
            text="When a network partition happens the leader cannot replicate log entries to the majority.",
        ),
        TranscriptSegment(
            id=2,
            start_seconds=30.0,
            end_seconds=50.0,
            duration_seconds=20.0,
            text="And that is why two-phase commit is never enough for true distributed fault tolerance.",
        ),
        TranscriptSegment(
            id=3,
            start_seconds=50.0,
            end_seconds=60.0,
            duration_seconds=10.0,
            text="Thank you everyone for listening and see you in the next episode.",
        ),
    ]


@pytest.fixture
def default_settings():
    return GenerationSettings(
        min_duration_seconds=10.0,
        preferred_min_seconds=15.0,
        preferred_max_seconds=45.0,
        target_duration_seconds=30.0,
        max_duration_seconds=60.0,
        candidate_pool_target=10,
        display_limit=5,
    )


def test_temporal_iou_calculation():
    # Identical
    assert compute_temporal_iou(10.0, 30.0, 10.0, 30.0) == 1.0
    # Disjoint
    assert compute_temporal_iou(0.0, 10.0, 20.0, 30.0) == 0.0
    # Partial overlap: [10, 30] and [20, 40] -> intersection=10, union=30 -> 10/30 = 0.333
    assert compute_temporal_iou(10.0, 30.0, 20.0, 40.0) == pytest.approx(10.0 / 30.0, 0.01)
    # High overlap: [10, 40] and [12, 38] -> intersection=26, union=30 -> 26/30 = 0.867
    assert compute_temporal_iou(10.0, 40.0, 12.0, 38.0) == pytest.approx(26.0 / 30.0, 0.01)


def test_candidate_duration_validation(sample_segments, default_settings):
    base_candidate = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=17.0,  # 7.0s duration (< 10.0s)
        hook="Short hook",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Short moment",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=15.0, quote="When a network partition happens the leader cannot replicate")],
        confidence_label=ConfidenceLabel.HIGH,
    )

    # 1. Below minimum duration (<10.0s) -> Must be REJECTED and invalid
    res = validate_candidate_against_transcript(
        base_candidate, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.DURATION_BELOW_MINIMUM in res.reason_codes
    assert any("below minimum" in r for r in res.reasons)

    # 2. Specific boundary cases below threshold
    for short_end in [15.28, 19.3, 19.99]:  # durations: 5.28s, 9.3s, 9.99s
        cand = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": short_end})
        c_res = validate_candidate_against_transcript(
            cand, sample_segments, default_settings, source_duration_seconds=60.0
        )
        assert c_res.is_valid is False
        assert c_res.status == ValidationStatus.REJECTED
        assert ValidationReasonCode.DURATION_BELOW_MINIMUM in c_res.reason_codes
        assert any("below minimum" in r for r in c_res.reasons)

    # 3. Exact minimum boundary (10.0s) -> Must be ACCEPTED and valid
    exact_min = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": 20.0})
    c_res = validate_candidate_against_transcript(
        exact_min, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert c_res.is_valid is True
    assert c_res.status == ValidationStatus.VALID
    assert ValidationReasonCode.DURATION_BELOW_MINIMUM not in c_res.reason_codes

    # 4. Valid duration above minimum (10.26s)
    valid_dur = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": 20.26})
    c_res = validate_candidate_against_transcript(
        valid_dur, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert c_res.is_valid is True
    assert c_res.status == ValidationStatus.VALID

    # 5. Exact maximum boundary (60.0s) -> Must be ACCEPTED
    exact_max = base_candidate.model_copy(update={"start_seconds": 0.0, "end_seconds": 60.0})
    c_res = validate_candidate_against_transcript(
        exact_max, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert c_res.is_valid is True
    assert c_res.status == ValidationStatus.VALID

    # 6. Exceeds maximum duration (60.01s > 60.0s) -> Must be REJECTED
    exceeds_max = base_candidate.model_copy(update={"start_seconds": 0.0, "end_seconds": 60.01})
    c_res = validate_candidate_against_transcript(
        exceeds_max, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert c_res.is_valid is False
    assert c_res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.DURATION_EXCEEDS_MAXIMUM in c_res.reason_codes
    assert any("exceeds maximum" in r for r in c_res.reasons)

    # 7. Exceeds source duration (65s > 60s source)
    overrun_candidate = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": 65.0})
    c_res = validate_candidate_against_transcript(
        overrun_candidate, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert c_res.is_valid is False
    assert c_res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.END_EXCEEDS_SOURCE in c_res.reason_codes
    assert any("exceeds source duration" in r for r in c_res.reasons)


def test_validation_reason_codes_comprehensive(sample_segments, default_settings):
    """Verify typed reason codes are emitted for every individual rejection condition."""
    base_candidate = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=30.0,
        hook="Valid hook",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Good moment",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=20.0, quote="When a network partition happens the leader cannot replicate")],
        confidence_label=ConfidenceLabel.HIGH,
    )

    # 1. Negative start time
    neg_start = base_candidate.model_copy(update={"start_seconds": -2.0, "end_seconds": 20.0})
    res = validate_candidate_against_transcript(neg_start, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.START_NEGATIVE in res.reason_codes

    # 2. End exceeds source duration
    end_over = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": 62.0})
    res = validate_candidate_against_transcript(end_over, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.END_EXCEEDS_SOURCE in res.reason_codes

    # 3. Non-positive duration
    zero_dur = base_candidate.model_copy(update={"start_seconds": 20.0, "end_seconds": 20.0})
    res = validate_candidate_against_transcript(zero_dur, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.DURATION_NON_POSITIVE in res.reason_codes

    # 4. Duration below minimum (<10s)
    short_dur = base_candidate.model_copy(update={"start_seconds": 10.0, "end_seconds": 18.0})
    res = validate_candidate_against_transcript(short_dur, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.DURATION_BELOW_MINIMUM in res.reason_codes

    # 5. Duration exceeds maximum (>60s)
    long_dur = base_candidate.model_copy(update={"start_seconds": 0.0, "end_seconds": 65.0})
    res = validate_candidate_against_transcript(long_dur, sample_segments, default_settings, 100.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.DURATION_EXCEEDS_MAXIMUM in res.reason_codes

    # 6. No evidence quotes
    no_ev = base_candidate.model_copy(update={"evidence": []})
    res = validate_candidate_against_transcript(no_ev, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.NO_EVIDENCE in res.reason_codes

    # 7. Hallucinated evidence (none grounded)
    hallucinated = base_candidate.model_copy(
        update={"evidence": [EvidenceItem(start_seconds=10.0, end_seconds=20.0, quote="Completely fabricated quote nonexistent")]}
    )
    res = validate_candidate_against_transcript(hallucinated, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes


def test_review_warning_vs_hard_rejection(sample_segments, default_settings):
    """Partially ungrounded evidence triggers review warning (NEEDS_REVIEW), not hard rejection."""
    candidate = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=30.0,
        hook="Partially grounded candidate",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="One real quote and one ungrounded quote",
        evidence=[
            # Grounded quote
            EvidenceItem(start_seconds=10.0, end_seconds=20.0, quote="When a network partition happens the leader cannot replicate"),
            # Hallucinated quote
            EvidenceItem(start_seconds=20.0, end_seconds=30.0, quote="The sky is green on planet Mars during sunset"),
        ],
        confidence_label=ConfidenceLabel.MEDIUM,
    )

    res = validate_candidate_against_transcript(candidate, sample_segments, default_settings, 60.0)
    assert res.is_valid is True
    assert res.status == ValidationStatus.NEEDS_REVIEW
    assert ValidationReasonCode.EVIDENCE_PARTIALLY_UNGROUNDED in res.reason_codes
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED not in res.reason_codes

    # Ensure ranking includes it as surviving candidate with status NEEDS_REVIEW
    ranking_res = deduplicate_and_rank_candidates(
        evaluations=[candidate],
        segments=sample_segments,
        editorial_goal=EditorialGoal.OVERALL,
        settings=default_settings,
        source_duration_seconds=60.0,
    )
    assert len(ranking_res.candidates) == 1
    assert ranking_res.candidates[0].validation_status == ValidationStatus.NEEDS_REVIEW
    assert len(ranking_res.rejected_candidates) == 0


def test_ranking_drops_sub_minimum_duration_candidates(sample_segments, default_settings):
    """End-to-end regression: candidates with duration < 10.0s are dropped by ranking and audited."""
    evaluations = [
        # Candidate 1: valid 10.26s (should survive)
        LLMCandidateEvaluation(
            start_seconds=10.0,
            end_seconds=20.26,
            hook="Valid candidate above minimum",
            transcript_excerpt="When a network partition happens...",
            score_dimensions=ScoreBreakdown(
                hook_strength=4.5, completeness_coherence=4.5, standalone_understandability=4.5,
                goal_relevance=4.5, goal_specific_impact=4.5, specificity_insight=4.5,
                pacing_conciseness=4.5, ending_quality=4.5,
            ),
            rationale="Valid length",
            evidence=[EvidenceItem(start_seconds=10.0, end_seconds=15.0, quote="When a network partition happens the leader cannot replicate")],
            confidence_label=ConfidenceLabel.HIGH,
        ),
        # Candidate 2: 5.28s (sub-minimum: must be dropped)
        LLMCandidateEvaluation(
            start_seconds=25.0,
            end_seconds=30.28,
            hook="Too short candidate 5.3s",
            transcript_excerpt="When a network partition happens...",
            score_dimensions=ScoreBreakdown(
                hook_strength=5.0, completeness_coherence=5.0, standalone_understandability=5.0,
                goal_relevance=5.0, goal_specific_impact=5.0, specificity_insight=5.0,
                pacing_conciseness=5.0, ending_quality=5.0,
            ),
            rationale="High score but too short",
            evidence=[EvidenceItem(start_seconds=25.0, end_seconds=28.0, quote="When a network partition happens the leader cannot replicate")],
            confidence_label=ConfidenceLabel.HIGH,
        ),
        # Candidate 3: 9.30s (sub-minimum: must be dropped)
        LLMCandidateEvaluation(
            start_seconds=35.0,
            end_seconds=44.30,
            hook="Too short candidate 9.3s",
            transcript_excerpt="And that is why two-phase commit...",
            score_dimensions=ScoreBreakdown(
                hook_strength=5.0, completeness_coherence=5.0, standalone_understandability=5.0,
                goal_relevance=5.0, goal_specific_impact=5.0, specificity_insight=5.0,
                pacing_conciseness=5.0, ending_quality=5.0,
            ),
            rationale="High score but too short",
            evidence=[EvidenceItem(start_seconds=35.0, end_seconds=40.0, quote="And that is why two-phase commit is never enough for true distributed fault tolerance")],
            confidence_label=ConfidenceLabel.HIGH,
        ),
    ]

    ranking_res = deduplicate_and_rank_candidates(
        evaluations=evaluations,
        segments=sample_segments,
        editorial_goal=EditorialGoal.EDUCATION,
        settings=default_settings,
        source_duration_seconds=60.0,
        iou_threshold=0.50,
    )

    ranked = ranking_res.candidates
    rejected = ranking_res.rejected_candidates

    # Only candidate 1 must survive
    assert len(ranked) == 1
    assert ranked[0].hook == "Valid candidate above minimum"
    assert ranked[0].duration_seconds == 10.26
    assert ranked[0].validation_status == ValidationStatus.VALID

    # Two candidates were dropped
    assert len(rejected) == 2
    assert rejected[0].hook == "Too short candidate 5.3s"
    assert rejected[0].duration_seconds == 5.28
    assert ValidationReasonCode.DURATION_BELOW_MINIMUM in rejected[0].reason_codes
    assert rejected[1].hook == "Too short candidate 9.3s"
    assert rejected[1].duration_seconds == 9.30
    assert ValidationReasonCode.DURATION_BELOW_MINIMUM in rejected[1].reason_codes


def test_ranking_info_level_logging_and_rejection_capture(sample_segments, default_settings, caplog):
    """Dropped candidates must be logged at INFO level with times, duration, hook, and reason codes."""
    short_candidate = LLMCandidateEvaluation(
        start_seconds=25.0,
        end_seconds=30.28,
        hook="Logging test candidate",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=5.0, completeness_coherence=5.0, standalone_understandability=5.0,
            goal_relevance=5.0, goal_specific_impact=5.0, specificity_insight=5.0,
            pacing_conciseness=5.0, ending_quality=5.0,
        ),
        rationale="Duration is 5.28s",
        evidence=[EvidenceItem(start_seconds=25.0, end_seconds=28.0, quote="When a network partition happens the leader cannot replicate")],
        confidence_label=ConfidenceLabel.HIGH,
    )

    with caplog.at_level(logging.INFO, logger="app.services.candidates.ranking"):
        ranking_res = deduplicate_and_rank_candidates(
            evaluations=[short_candidate],
            segments=sample_segments,
            editorial_goal=EditorialGoal.OVERALL,
            settings=default_settings,
            source_duration_seconds=60.0,
        )

    assert len(ranking_res.candidates) == 0
    assert len(ranking_res.rejected_candidates) == 1

    # Verify INFO log message format
    info_records = [r for r in caplog.records if r.levelno == logging.INFO and "Dropping rejected candidate" in r.message]
    assert len(info_records) == 1
    log_text = info_records[0].message
    assert "[25.0s - 30.3s]" in log_text
    assert "duration=5.3s" in log_text
    assert "Logging test candidate" in log_text
    assert "DURATION_BELOW_MINIMUM" in log_text


def test_candidate_evidence_grounding(sample_segments, default_settings):
    # Valid grounded quote
    valid_candidate = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=35.0,
        hook="Network partition consensus",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.5, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.5, goal_specific_impact=4.0, specificity_insight=4.5,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Grounded quote",
        evidence=[
            EvidenceItem(
                start_seconds=10.0,
                end_seconds=20.0,
                quote="When a network partition happens the leader cannot replicate",
            )
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(
        valid_candidate, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID
    assert len(res.reasons) == 0
    assert len(res.reason_codes) == 0

    # Hallucinated quote
    hallucinated_candidate = valid_candidate.model_copy(
        update={
            "evidence": [
                EvidenceItem(
                    start_seconds=10.0,
                    end_seconds=20.0,
                    quote="Quantum computers break RSA encryption easily",
                )
            ]
        }
    )
    res = validate_candidate_against_transcript(
        hallucinated_candidate, sample_segments, default_settings, source_duration_seconds=60.0
    )
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes
    assert any("None of the candidate evidence quotes" in r for r in res.reasons)


def test_deduplication_prefers_higher_score_and_tie_breaking(sample_segments, default_settings):
    # Candidate A: [10, 40] (30s) score=90
    cand_a = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=40.0,
        hook="Higher score moment",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=5.0, completeness_coherence=5.0, standalone_understandability=5.0,
            goal_relevance=4.5, goal_specific_impact=4.5, specificity_insight=4.5,
            pacing_conciseness=4.5, ending_quality=4.0,
        ),
        rationale="Strong",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=20.0, quote="When a network partition happens")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    # Candidate B: [12, 42] (30s) overlaps A heavily (IoU ~ 0.88), but lower score=60
    cand_b = LLMCandidateEvaluation(
        start_seconds=12.0,
        end_seconds=42.0,
        hook="Lower score duplicate",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=3.0, completeness_coherence=3.0, standalone_understandability=3.0,
            goal_relevance=3.0, goal_specific_impact=3.0, specificity_insight=3.0,
            pacing_conciseness=3.0, ending_quality=3.0,
        ),
        rationale="Weaker",
        evidence=[EvidenceItem(start_seconds=12.0, end_seconds=20.0, quote="When a network partition happens")],
        confidence_label=ConfidenceLabel.MEDIUM,
    )
    # Candidate C: [35, 58] (23s) distinct moment, low overlap with A (IoU = 5/48 = 0.10)
    cand_c = LLMCandidateEvaluation(
        start_seconds=35.0,
        end_seconds=58.0,
        hook="Distinct moment",
        transcript_excerpt="two-phase commit is never enough...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Distinct",
        evidence=[EvidenceItem(start_seconds=35.0, end_seconds=45.0, quote="two-phase commit is never enough")],
        confidence_label=ConfidenceLabel.HIGH,
    )

    ranking_res = deduplicate_and_rank_candidates(
        evaluations=[cand_b, cand_a, cand_c],  # Note cand_b is passed first
        segments=sample_segments,
        editorial_goal=EditorialGoal.OVERALL,
        settings=default_settings,
        source_duration_seconds=60.0,
        iou_threshold=0.50,
    )
    ranked = ranking_res.candidates

    # Cand B must be suppressed because of high IoU with Cand A, and Cand A has higher score
    assert len(ranked) == 2
    assert ranked[0].hook == "Higher score moment"
    assert ranked[0].overall_score > ranked[1].overall_score
    assert ranked[1].hook == "Distinct moment"


def make_sample_source_media():
    return SourceMediaMetadata(
        filename="test.mp4",
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        duration_seconds=60.0,
        size_bytes=1048576,
        video_streams_count=1,
        audio_streams_count=1,
        selected_audio_stream_index=0,
        audio_codec="aac",
        audio_sample_rate=44100,
        audio_channels=2,
    )


def test_candidate_artifact_serialization_with_zero_valid_candidates(tmp_path, sample_segments, default_settings):
    """When all raw candidates are rejected, candidates.json has candidates_count: 0 and full diagnostics."""
    rejected_evaluations = [
        LLMCandidateEvaluation(
            start_seconds=10.0,
            end_seconds=15.0,  # 5.0s < 10.0s
            hook="Rejected candidate 1",
            transcript_excerpt="Excerpt 1",
            score_dimensions=ScoreBreakdown(
                hook_strength=3.0, completeness_coherence=3.0, standalone_understandability=3.0,
                goal_relevance=3.0, goal_specific_impact=3.0, specificity_insight=3.0,
                pacing_conciseness=3.0, ending_quality=3.0,
            ),
            rationale="Sub-minimum length",
            evidence=[EvidenceItem(start_seconds=10.0, end_seconds=15.0, quote="When a network partition happens")],
            confidence_label=ConfidenceLabel.LOW,
        ),
        LLMCandidateEvaluation(
            start_seconds=20.0,
            end_seconds=28.0,  # 8.0s < 10.0s
            hook="Rejected candidate 2",
            transcript_excerpt="Excerpt 2",
            score_dimensions=ScoreBreakdown(
                hook_strength=3.0, completeness_coherence=3.0, standalone_understandability=3.0,
                goal_relevance=3.0, goal_specific_impact=3.0, specificity_insight=3.0,
                pacing_conciseness=3.0, ending_quality=3.0,
            ),
            rationale="Sub-minimum length",
            evidence=[EvidenceItem(start_seconds=20.0, end_seconds=25.0, quote="When a network partition happens")],
            confidence_label=ConfidenceLabel.LOW,
        ),
    ]

    ranking_res = deduplicate_and_rank_candidates(
        evaluations=rejected_evaluations,
        segments=sample_segments,
        editorial_goal=EditorialGoal.HUMOR,
        settings=default_settings,
        source_duration_seconds=60.0,
    )

    assert len(ranking_res.candidates) == 0
    assert len(ranking_res.rejected_candidates) == 2

    artifact = CandidateArtifact(
        schema_version="v1.0",
        source_media=make_sample_source_media(),
        generation=CandidateGenerationMetadata(
            editorial_goal=EditorialGoal.HUMOR,
            provider="ollama",
            model="qwen2.5:7b",
            scoring_version="v1.0",
            settings=default_settings,
            chunks_processed=1,
            total_raw_candidates=2,
            rejected_candidates=ranking_res.rejected_candidates,
        ),
        candidates_count=len(ranking_res.candidates),
        candidates=ranking_res.candidates,
    )

    output_path = tmp_path / "candidates.json"
    written_path = write_candidate_artifact(artifact, output_path)
    assert written_path.exists()

    # Read back and verify artifact schema and diagnostics
    content = json.loads(written_path.read_text(encoding="utf-8"))
    assert content["candidates_count"] == 0
    assert content["candidates"] == []
    assert "rejected_candidates" in content["generation"]
    assert len(content["generation"]["rejected_candidates"]) == 2

    rej_0 = content["generation"]["rejected_candidates"][0]
    assert rej_0["hook"] == "Rejected candidate 1"
    assert rej_0["duration_seconds"] == 5.0
    assert rej_0["reason_codes"] == ["DURATION_BELOW_MINIMUM"]
    assert any("below minimum" in r for r in rej_0["reasons"])


def test_backward_compatibility_loading_artifact_without_rejected_candidates():
    """Existing candidates.json artifacts lacking rejected_candidates in generation must parse cleanly."""
    legacy_json_dict = {
        "schema_version": "v1.0",
        "created_at": "2026-10-20T00:00:00Z",
        "source_media": make_sample_source_media().model_dump(),
        "generation": {
            "editorial_goal": "overall",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "scoring_version": "v1.0",
            "settings": {
                "min_duration_seconds": 10.0,
                "preferred_min_seconds": 15.0,
                "preferred_max_seconds": 45.0,
                "target_duration_seconds": 30.0,
                "max_duration_seconds": 60.0,
                "candidate_pool_target": 10,
                "display_limit": 5,
            },
            "chunks_processed": 1,
            "total_raw_candidates": 1,
        },
        "candidates_count": 0,
        "candidates": [],
    }

    # Validate against Pydantic model
    parsed = CandidateArtifact.model_validate(legacy_json_dict)
    assert parsed.candidates_count == 0
    assert parsed.candidates == []
    assert parsed.generation.rejected_candidates == []


def test_grounding_punctuation_capitalization_and_ellipses(sample_segments, default_settings):
    """Quotes with capitalization differences, punctuation, and ellipses must ground successfully."""
    # Segment 1 has: "When a network partition happens the leader cannot replicate log entries to the majority."
    # Segment 2 has: "And that is why two-phase commit is never enough for true distributed fault tolerance."
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=50.0,
        hook="Punctuation normalization test",
        transcript_excerpt="When a network partition happens...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="test",
        evidence=[
            EvidenceItem(
                start_seconds=10.0,
                end_seconds=25.0,
                quote="WHEN A NETWORK PARTITION HAPPENS, THE LEADER CANNOT REPLICATE...",
            ),
            EvidenceItem(
                start_seconds=30.0,
                end_seconds=50.0,
                # Segment 2 has: "And that is why two-phase commit is never enough for true distributed fault tolerance."
                # Test hyphen vs space normalization
                quote="two phase commit is never enough...",
            ),
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, sample_segments, default_settings, 60.0)
    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID
    assert len(res.reason_codes) == 0


def test_grounding_quote_elsewhere_in_transcript_fails(sample_segments, default_settings):
    """A quote that exists elsewhere in the video but not in the candidate region must fail grounding."""
    # Candidate window is [10.0s, 30.0s], but quote is from segment 3 [50.0s, 60.0s]
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=30.0,
        hook="Misplaced evidence quote",
        transcript_excerpt="Excerpt",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="test",
        evidence=[
            EvidenceItem(
                start_seconds=10.0,
                end_seconds=25.0,
                quote="Thank you everyone for listening and see you in the next episode",
            )
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes


def test_grounding_genuinely_fabricated_quote_fails(sample_segments, default_settings):
    """A completely fabricated quote not anywhere in the transcript must fail grounding."""
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=30.0,
        hook="Fabricated evidence quote",
        transcript_excerpt="Excerpt",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="test",
        evidence=[
            EvidenceItem(
                start_seconds=10.0,
                end_seconds=25.0,
                quote="Alien spaceships were sighted landing in Central Park yesterday",
            )
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, sample_segments, default_settings, 60.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes


def test_system_prompt_candidate_boundary_and_duration_instructions(default_settings):
    """The system prompt must clearly instruct segment-based anchor selection for short mode and duration bounds for long mode."""
    # Test short anchor prompt
    short_prompt = build_system_prompt(EditorialGoal.HUMOR, default_settings, is_long_clip=False)
    assert "anchor_segment_ids" in short_prompt
    assert "Do NOT calculate timestamps" in short_prompt
    assert "HUMOR" in short_prompt

    # Test long clip prompt
    long_prompt = build_system_prompt(EditorialGoal.HUMOR, default_settings, is_long_clip=True)
    assert "30.0 <= (end_seconds - start_seconds) <= 60.0" in long_prompt or "Hard duration limits" in long_prompt
    assert "STANDALONE CONVERSATIONAL ARCS" in long_prompt


# ---------------------------------------------------------------------------
# Deterministic Tests for Candidate Evidence-to-Clip Temporal Grounding
# ---------------------------------------------------------------------------

@pytest.fixture
def temporal_grounding_segments():
    """Deterministic segments with explicit word timings to verify boundary checks."""
    return [
        TranscriptSegment(
            id=0,
            start_seconds=0.0,
            end_seconds=10.0,
            duration_seconds=10.0,
            text="Intro segment here.",
            words=[
                WordTiming(start_seconds=0.0, end_seconds=3.0, word="Intro"),
                WordTiming(start_seconds=3.0, end_seconds=6.0, word="segment"),
                WordTiming(start_seconds=6.0, end_seconds=10.0, word="here"),
            ],
        ),
        TranscriptSegment(
            id=1,
            start_seconds=10.0,
            end_seconds=30.0,
            duration_seconds=20.0,
            text="When network partitions occur distributed leaders fail to replicate log entries properly.",
            words=[
                WordTiming(start_seconds=10.0, end_seconds=12.0, word="When"),
                WordTiming(start_seconds=12.0, end_seconds=14.0, word="network"),
                WordTiming(start_seconds=14.0, end_seconds=16.0, word="partitions"),
                WordTiming(start_seconds=16.0, end_seconds=18.0, word="occur"),
                WordTiming(start_seconds=18.0, end_seconds=20.0, word="distributed"),
                WordTiming(start_seconds=20.0, end_seconds=22.0, word="leaders"),
                WordTiming(start_seconds=22.0, end_seconds=24.0, word="fail"),
                WordTiming(start_seconds=24.0, end_seconds=26.0, word="to"),
                WordTiming(start_seconds=26.0, end_seconds=27.0, word="replicate"),
                WordTiming(start_seconds=27.0, end_seconds=28.5, word="log"),
                WordTiming(start_seconds=28.5, end_seconds=29.2, word="entries"),
                WordTiming(start_seconds=29.2, end_seconds=30.0, word="properly"),
            ],
        ),
        TranscriptSegment(
            id=2,
            start_seconds=30.0,
            end_seconds=50.0,
            duration_seconds=20.0,
            text="Two phase commit never guarantees resilience under asynchronous network delay.",
            words=[
                WordTiming(start_seconds=30.0, end_seconds=32.0, word="Two"),
                WordTiming(start_seconds=32.0, end_seconds=34.0, word="phase"),
                WordTiming(start_seconds=34.0, end_seconds=36.0, word="commit"),
                WordTiming(start_seconds=36.0, end_seconds=38.0, word="never"),
                WordTiming(start_seconds=38.0, end_seconds=40.0, word="guarantees"),
                WordTiming(start_seconds=40.0, end_seconds=42.0, word="resilience"),
                WordTiming(start_seconds=42.0, end_seconds=44.0, word="under"),
                WordTiming(start_seconds=44.0, end_seconds=46.0, word="asynchronous"),
                WordTiming(start_seconds=46.0, end_seconds=48.0, word="network"),
                WordTiming(start_seconds=48.0, end_seconds=50.0, word="delay"),
            ],
        ),
        TranscriptSegment(
            id=3,
            start_seconds=50.0,
            end_seconds=70.0,
            duration_seconds=20.0,
            text="And that concludes our distributed consensus summary today.",
            words=[
                WordTiming(start_seconds=50.0, end_seconds=53.0, word="And"),
                WordTiming(start_seconds=53.0, end_seconds=56.0, word="that"),
                WordTiming(start_seconds=56.0, end_seconds=60.0, word="concludes"),
                WordTiming(start_seconds=60.0, end_seconds=64.0, word="our"),
                WordTiming(start_seconds=64.0, end_seconds=67.0, word="distributed"),
                WordTiming(start_seconds=67.0, end_seconds=68.5, word="consensus"),
                WordTiming(start_seconds=68.5, end_seconds=69.5, word="summary"),
                WordTiming(start_seconds=69.5, end_seconds=70.0, word="today"),
            ],
        ),
    ]


def test_temporal_grounding_evidence_inside_candidate_interval_accepted(temporal_grounding_segments, default_settings):
    """Case 1: Evidence quote fully contained within candidate interval is accepted as VALID."""
    # Candidate: [10.0, 30.0]
    # Quote: "When network partitions occur" (exact word timing: [10.0, 18.0])
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=30.0,
        hook="Network partition failure",
        transcript_excerpt="When network partitions occur...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.5, completeness_coherence=4.5, standalone_understandability=4.5,
            goal_relevance=4.5, goal_specific_impact=4.5, specificity_insight=4.5,
            pacing_conciseness=4.5, ending_quality=4.5,
        ),
        rationale="Inside interval",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=18.0, quote="When network partitions occur")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, temporal_grounding_segments, default_settings, 100.0)
    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID
    assert len(res.reason_codes) == 0


def test_temporal_grounding_evidence_straddling_boundary_within_tolerance_accepted(temporal_grounding_segments, default_settings):
    """Case 2: Evidence straddling clip boundary with non-zero overlap and spillover <= tolerance is accepted."""
    # Candidate: [15.0, 30.0] (duration 15.0s)
    # Quote: "When network partitions occur distributed leaders" (words: [10.0, 22.0])
    # Overlap with [15.0, 30.0]: [15.0, 22.0] = 7.0s > 0.
    # Lead outside candidate start: 15.0 - 10.0 = 5.0s <= 5.0s tolerance.
    # Trail outside candidate end: max(0, 22.0 - 30.0) = 0.0s <= 5.0s.
    cand = LLMCandidateEvaluation(
        start_seconds=15.0,
        end_seconds=30.0,
        hook="Straddling boundary quote within tolerance",
        transcript_excerpt="When network partitions occur...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Boundary straddle within tolerance",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=22.0, quote="When network partitions occur distributed leaders")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, temporal_grounding_segments, default_settings, 100.0, quote_tolerance_seconds=5.0)
    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID
    assert len(res.reason_codes) == 0


def test_temporal_grounding_evidence_entirely_outside_candidate_rejected(temporal_grounding_segments, default_settings):
    """Case 3: Evidence quote entirely outside candidate clip (zero overlap) is rejected with EVIDENCE_NOT_GROUNDED."""
    # Candidate: [10.0, 28.0]
    # Quote: "Two phase commit never guarantees" from segment 2 (words: [30.0, 40.0])
    # Quote starts at 30.0s, which is 2.0s after candidate end (30.0 <= 28.0 + 5.0 tolerance window).
    # However, overlap = min(40.0, 28.0) - max(30.0, 10.0) = 28.0 - 30.0 = -2.0 <= 0 (disjoint!).
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=28.0,
        hook="Disjoint quote in adjacent segment",
        transcript_excerpt="When network partitions occur...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Disjoint quote outside clip",
        evidence=[EvidenceItem(start_seconds=30.0, end_seconds=40.0, quote="Two phase commit never guarantees")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, temporal_grounding_segments, default_settings, 100.0, quote_tolerance_seconds=5.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes
    assert any("not contained within candidate interval" in r for r in res.reasons)


def test_temporal_grounding_crossing_segment_cannot_bypass_temporal_checks(temporal_grounding_segments, default_settings):
    """Case 4: A segment crossing the expanded window boundary cannot bypass temporal checks."""
    # Candidate: [10.0, 26.0]
    # Tolerance: 5.0s -> expanded window [5.0, 31.0].
    # Segment 2 [30.0, 50.0] starts at 30.0s <= 31.0s, so it overlaps the expanded window.
    # Quote: "asynchronous network delay" is at the TAIL of Segment 2 (words: [44.0, 50.0]).
    # Under old logic, because Segment 2 was in local_segments, all its text was matched!
    # Under temporal validation, words are at [44.0, 50.0], which is 18s past candidate end (trail=24s > 5s, overlap <= 0).
    cand = LLMCandidateEvaluation(
        start_seconds=10.0,
        end_seconds=26.0,
        hook="Tail of crossing segment quote",
        transcript_excerpt="When network partitions occur...",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Crossing segment bypass attempt",
        evidence=[EvidenceItem(start_seconds=44.0, end_seconds=50.0, quote="asynchronous network delay")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res = validate_candidate_against_transcript(cand, temporal_grounding_segments, default_settings, 100.0, quote_tolerance_seconds=5.0)
    assert res.is_valid is False
    assert res.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res.reason_codes
    assert any("not contained within candidate interval" in r for r in res.reasons)


def test_anne_hathaway_candidates_deterministic_regression():
    """Case 5: Exact regression test for Anne Hathaway Candidate 1 (rejected) and Candidate 2 (accepted)."""
    # Build transcript segments mimicking Anne Hathaway interview:
    # Segment 23: [90.48, 98.70] "And so I said, 'Well, do you remember...'"
    # Segment 24: [98.70, 105.12] "And she's like, 'No, I don't remember that at all.'"
    # Segment 25: [105.12, 111.84] "And then we had this other thing happen."
    # Segment 26: [111.84, 118.74] "I'm gonna say wait, but I was genuinely confused. Wait, but it's her that was me, but I'm the is it that's wild"
    #   Word timings for quote: [115.04, 118.74]
    # Segment 58: [254.12, 256.54] "I said you know I saw you by the way"
    # Segment 59: [256.54, 275.22] "And it was at the party and everybody was laughing..."
    segments = [
        TranscriptSegment(
            id=23, start_seconds=90.48, end_seconds=98.70, duration_seconds=8.22,
            text="And so I said, 'Well, do you remember...'",
        ),
        TranscriptSegment(
            id=24, start_seconds=98.70, end_seconds=105.12, duration_seconds=6.42,
            text="And she's like, 'No, I don't remember that at all.'",
        ),
        TranscriptSegment(
            id=25, start_seconds=105.12, end_seconds=111.84, duration_seconds=6.72,
            text="And then we had this other thing happen.",
        ),
        TranscriptSegment(
            id=26, start_seconds=111.84, end_seconds=118.74, duration_seconds=6.90,
            text="I'm gonna say wait, but I was genuinely confused. Wait, but it's her that was me, but I'm the is it that's wild",
            words=[
                WordTiming(start_seconds=111.84, end_seconds=112.50, word="I'm"),
                WordTiming(start_seconds=112.50, end_seconds=113.00, word="gonna"),
                WordTiming(start_seconds=113.00, end_seconds=113.50, word="say"),
                WordTiming(start_seconds=113.50, end_seconds=114.00, word="wait"),
                WordTiming(start_seconds=114.00, end_seconds=114.50, word="but"),
                WordTiming(start_seconds=114.50, end_seconds=114.80, word="I"),
                WordTiming(start_seconds=114.80, end_seconds=115.00, word="was"),
                WordTiming(start_seconds=115.00, end_seconds=115.04, word="genuinely"),
                WordTiming(start_seconds=115.04, end_seconds=115.50, word="confused"),
                WordTiming(start_seconds=115.50, end_seconds=115.80, word="Wait"),
                WordTiming(start_seconds=115.80, end_seconds=116.00, word="but"),
                WordTiming(start_seconds=116.00, end_seconds=116.30, word="it's"),
                WordTiming(start_seconds=116.30, end_seconds=116.60, word="her"),
                WordTiming(start_seconds=116.60, end_seconds=116.90, word="that"),
                WordTiming(start_seconds=116.90, end_seconds=117.10, word="was"),
                WordTiming(start_seconds=117.10, end_seconds=117.40, word="me"),
                WordTiming(start_seconds=117.40, end_seconds=117.70, word="but"),
                WordTiming(start_seconds=117.70, end_seconds=118.00, word="I'm"),
                WordTiming(start_seconds=118.00, end_seconds=118.20, word="the"),
                WordTiming(start_seconds=118.20, end_seconds=118.40, word="is"),
                WordTiming(start_seconds=118.40, end_seconds=118.60, word="it"),
                WordTiming(start_seconds=118.60, end_seconds=118.70, word="that's"),
                WordTiming(start_seconds=118.70, end_seconds=118.74, word="wild"),
            ],
        ),
        TranscriptSegment(
            id=58, start_seconds=254.12, end_seconds=256.54, duration_seconds=2.42,
            text="I said you know I saw you by the way",
            words=[
                WordTiming(start_seconds=254.12, end_seconds=254.40, word="I"),
                WordTiming(start_seconds=254.40, end_seconds=254.70, word="said"),
                WordTiming(start_seconds=254.70, end_seconds=255.00, word="you"),
                WordTiming(start_seconds=255.00, end_seconds=255.30, word="know"),
                WordTiming(start_seconds=255.30, end_seconds=255.60, word="I"),
                WordTiming(start_seconds=255.60, end_seconds=255.90, word="saw"),
                WordTiming(start_seconds=255.90, end_seconds=256.20, word="you"),
                WordTiming(start_seconds=256.20, end_seconds=256.40, word="by"),
                WordTiming(start_seconds=256.40, end_seconds=256.50, word="the"),
                WordTiming(start_seconds=256.50, end_seconds=256.54, word="way"),
            ],
        ),
        TranscriptSegment(
            id=59, start_seconds=256.54, end_seconds=275.22, duration_seconds=18.68,
            text="And it was at the party and everybody was laughing about the movie.",
        ),
    ]

    settings = GenerationSettings()

    # Candidate 1: interval [90.48, 107.48], quote is at [115.50, 118.74] (zero overlap, 8s past clip end)
    cand1 = LLMCandidateEvaluation(
        start_seconds=90.48,
        end_seconds=107.48,
        hook="Wait, but it's her that was me, but I'm the is it that's wild",
        transcript_excerpt="Wait, but it's her that was me, but I'm the is it that's wild",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.5, completeness_coherence=4.0, standalone_understandability=4.5,
            goal_relevance=4.5, goal_specific_impact=4.5, specificity_insight=4.0,
            pacing_conciseness=4.5, ending_quality=4.5,
        ),
        rationale="Funny reaction",
        evidence=[
            EvidenceItem(
                start_seconds=90.48,
                end_seconds=107.48,
                quote="Wait, but it's her that was me, but I'm the is it that's wild",
            )
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res1 = validate_candidate_against_transcript(cand1, segments, settings, 622.84, quote_tolerance_seconds=5.0)
    # Must be REJECTED!
    assert res1.is_valid is False
    assert res1.status == ValidationStatus.REJECTED
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res1.reason_codes
    assert any("not contained within candidate interval" in r for r in res1.reasons)

    # Candidate 2: interval [254.12, 275.22], quote is at [254.12, 256.54] (100% inside clip)
    cand2 = LLMCandidateEvaluation(
        start_seconds=254.12,
        end_seconds=275.22,
        hook="I said you know I saw you by the way",
        transcript_excerpt="I said you know I saw you by the way",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Party encounter story",
        evidence=[
            EvidenceItem(
                start_seconds=254.12,
                end_seconds=275.22,
                quote="I said you know I saw you by the way",
            )
        ],
        confidence_label=ConfidenceLabel.HIGH,
    )
    res2 = validate_candidate_against_transcript(cand2, segments, settings, 622.84, quote_tolerance_seconds=5.0)
    # Must be ACCEPTED!
    assert res2.is_valid is True
    assert res2.status == ValidationStatus.VALID
    assert len(res2.reason_codes) == 0
