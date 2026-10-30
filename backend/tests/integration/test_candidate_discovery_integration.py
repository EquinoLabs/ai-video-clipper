"""Integration tests for Phase 2 candidate discovery CLI using a mock LLM provider."""

import json
from pathlib import Path
import pytest
from app.domain.candidates.models import (
    CandidateArtifact,
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    LLMCandidateEvaluation,
    ScoreBreakdown,
)
from app.services.candidates.discovery import run_candidate_discovery
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
)
from app.services.llm.base import LLMProvider


class MockLLMProvider(LLMProvider):
    """Deterministic mock LLM provider that simulates structured OpenAI responses."""

    def __init__(self, candidates_to_return=None):
        self.candidates_to_return = candidates_to_return or []

    async def discover_and_evaluate(
        self,
        transcript_segments,
        editorial_goal,
        settings,
        custom_instructions=None,
        target_count=None,
        is_long_clip=False,
    ):
        return self.candidates_to_return


@pytest.fixture
def mock_transcript_file(tmp_path: Path) -> Path:
    transcript_path = tmp_path / "test_transcript.json"
    artifact = TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="test_interview.mp4",
            format_name="mov,mp4",
            duration_seconds=120.0,
            size_bytes=1000000,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="faster-whisper",
            model="tiny",
            language="en",
            word_timestamps_enabled=True,
            duration_processed_seconds=120.0,
        ),
        word_timestamps_available=True,
        segment_count=4,
        total_words_count=80,
        segments=[
            TranscriptSegment(
                id=0,
                start_seconds=0.0,
                end_seconds=30.0,
                duration_seconds=30.0,
                text="Welcome everyone. In today's video we will explain why system design interviews focus on scalability.",
            ),
            TranscriptSegment(
                id=1,
                start_seconds=30.0,
                end_seconds=60.0,
                duration_seconds=30.0,
                text="When databases reach millions of queries per second caching with Redis becomes mandatory.",
            ),
            TranscriptSegment(
                id=2,
                start_seconds=60.0,
                end_seconds=90.0,
                duration_seconds=30.0,
                text="However cache invalidation is one of the two hardest problems in computer science.",
            ),
            TranscriptSegment(
                id=3,
                start_seconds=90.0,
                end_seconds=120.0,
                duration_seconds=30.0,
                text="Thank you for watching and remember to subscribe for more engineering tutorials.",
            ),
        ],
    )
    transcript_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return transcript_path


@pytest.mark.asyncio
async def test_full_candidate_discovery_pipeline_with_mock_llm(mock_transcript_file: Path, monkeypatch, tmp_path: Path):
    mock_candidates = [
        LLMCandidateEvaluation(
            start_seconds=30.0,
            end_seconds=65.0,
            hook="Why caching with Redis is mandatory at scale",
            transcript_excerpt="When databases reach millions of queries per second...",
            score_dimensions=ScoreBreakdown(
                hook_strength=4.8, completeness_coherence=4.5, standalone_understandability=4.5,
                goal_relevance=4.8, goal_specific_impact=4.5, specificity_insight=4.8,
                pacing_conciseness=4.2, ending_quality=4.0,
            ),
            rationale="High technical insight with clear explanation and relevance.",
            evidence=[
                EvidenceItem(
                    start_seconds=30.0,
                    end_seconds=45.0,
                    quote="When databases reach millions of queries per second caching with Redis",
                )
            ],
            confidence_label=ConfidenceLabel.HIGH,
        ),
        LLMCandidateEvaluation(
            start_seconds=60.0,
            end_seconds=88.0,
            hook="The hardest problem in computer science",
            transcript_excerpt="However cache invalidation is one of the two hardest problems...",
            score_dimensions=ScoreBreakdown(
                hook_strength=4.2, completeness_coherence=4.0, standalone_understandability=4.2,
                goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
                pacing_conciseness=4.0, ending_quality=4.0,
            ),
            rationale="Famous computer science quote with great hook.",
            evidence=[
                EvidenceItem(
                    start_seconds=60.0,
                    end_seconds=75.0,
                    quote="However cache invalidation is one of the two hardest problems",
                )
            ],
            confidence_label=ConfidenceLabel.HIGH,
        ),
    ]

    mock_provider = MockLLMProvider(mock_candidates)
    monkeypatch.setattr("app.services.candidates.discovery.get_llm_provider", lambda **kwargs: mock_provider)

    output_dir = tmp_path / "candidates_out"
    saved_path = await run_candidate_discovery(
        transcript_path=mock_transcript_file,
        output_dir=output_dir,
        editorial_goal=EditorialGoal.EDUCATION,
    )

    assert saved_path.exists()
    assert saved_path.name == "candidates.json"

    # Verify deserialization into CandidateArtifact
    candidate_data = json.loads(saved_path.read_text(encoding="utf-8"))
    artifact = CandidateArtifact.model_validate(candidate_data)

    assert artifact.schema_version == "v1.0"
    assert artifact.source_media.filename == "test_interview.mp4"
    assert artifact.generation.editorial_goal == EditorialGoal.EDUCATION
    assert artifact.generation.scoring_version == "v1.0"
    assert artifact.candidates_count == 2
    assert len(artifact.candidates) == 2

    # Verify rank and score ordering
    top_cand = artifact.candidates[0]
    assert top_cand.id == "cnd_001"
    assert top_cand.overall_score >= artifact.candidates[1].overall_score
    assert top_cand.duration_seconds == 35.0
    assert artifact.candidates[1].id == "cnd_002"
    assert artifact.candidates[1].duration_seconds == 28.0


@pytest.mark.asyncio
async def test_multi_window_candidate_discovery_merging_and_deduplication(tmp_path: Path, monkeypatch):
    """Multiple chunks pass target_count to provider and merge/deduplicate overlapping candidates."""
    received_targets = []

    class MultiWindowMockProvider(LLMProvider):
        def __init__(self):
            pass

        async def discover_and_evaluate(
            self,
            transcript_segments,
            editorial_goal,
            settings,
            custom_instructions=None,
            target_count=None,
        is_long_clip=False,
        ):
            received_targets.append(target_count)
            # If this is window 1 (starts at 0.0), return candidate A at [0.0, 25.0]
            if transcript_segments[0].start_seconds == 0.0:
                return [
                    LLMCandidateEvaluation(
                        start_seconds=0.0,
                        end_seconds=25.0,
                        hook="Window 1 moment",
                        transcript_excerpt="When databases reach millions...",
                        score_dimensions=ScoreBreakdown(
                            hook_strength=4.5, completeness_coherence=4.0, standalone_understandability=4.5,
                            goal_relevance=4.5, goal_specific_impact=4.5, specificity_insight=4.5,
                            pacing_conciseness=4.0, ending_quality=4.0,
                        ),
                        rationale="Strong window 1 moment",
                        evidence=[
                            EvidenceItem(
                                start_seconds=0.0,
                                end_seconds=20.0,
                                quote="When databases reach millions of queries per second",
                            )
                        ],
                        confidence_label=ConfidenceLabel.HIGH,
                    ),
                    # Duplicate near boundary: [30.0, 58.0]
                    LLMCandidateEvaluation(
                        start_seconds=30.0,
                        end_seconds=58.0,
                        hook="Duplicate boundary candidate W1",
                        transcript_excerpt="However cache invalidation...",
                        score_dimensions=ScoreBreakdown(
                            hook_strength=3.5, completeness_coherence=3.5, standalone_understandability=3.5,
                            goal_relevance=3.5, goal_specific_impact=3.5, specificity_insight=3.5,
                            pacing_conciseness=3.5, ending_quality=3.5,
                        ),
                        rationale="Lower score duplicate",
                        evidence=[
                            EvidenceItem(
                                start_seconds=30.0,
                                end_seconds=50.0,
                                quote="However cache invalidation is one of the two hardest problems",
                            )
                        ],
                        confidence_label=ConfidenceLabel.MEDIUM,
                    ),
                ]
            else:
                # Window 2: returns higher-scoring version of boundary moment [30.0, 58.0] and distinct moment [65.0, 95.0]
                return [
                    LLMCandidateEvaluation(
                        start_seconds=30.0,
                        end_seconds=58.0,
                        hook="Duplicate boundary candidate W2 higher score",
                        transcript_excerpt="However cache invalidation...",
                        score_dimensions=ScoreBreakdown(
                            hook_strength=4.8, completeness_coherence=4.8, standalone_understandability=4.8,
                            goal_relevance=4.8, goal_specific_impact=4.8, specificity_insight=4.8,
                            pacing_conciseness=4.8, ending_quality=4.8,
                        ),
                        rationale="Higher score duplicate",
                        evidence=[
                            EvidenceItem(
                                start_seconds=30.0,
                                end_seconds=50.0,
                                quote="However cache invalidation is one of the two hardest problems",
                            )
                        ],
                        confidence_label=ConfidenceLabel.HIGH,
                    ),
                    LLMCandidateEvaluation(
                        start_seconds=65.0,
                        end_seconds=95.0,
                        hook="Window 2 distinct moment",
                        transcript_excerpt="And distributed systems require...",
                        score_dimensions=ScoreBreakdown(
                            hook_strength=4.2, completeness_coherence=4.0, standalone_understandability=4.0,
                            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
                            pacing_conciseness=4.0, ending_quality=4.0,
                        ),
                        rationale="Distinct moment in window 2",
                        evidence=[
                            EvidenceItem(
                                start_seconds=65.0,
                                end_seconds=90.0,
                                quote="And distributed systems require consensus",
                            )
                        ],
                        confidence_label=ConfidenceLabel.HIGH,
                    ),
                ]

    # Create a transcript with 2 chunks by using chunk_size_words=30
    segments = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, text="When databases reach millions of queries per second caching with Redis is essential."),
        TranscriptSegment(id=1, start_seconds=30.0, end_seconds=60.0, duration_seconds=30.0, text="However cache invalidation is one of the two hardest problems in computer science."),
        TranscriptSegment(id=2, start_seconds=60.0, end_seconds=100.0, duration_seconds=40.0, text="And distributed systems require consensus protocols like Raft or Paxos to stay consistent."),
    ]
    transcript_path = tmp_path / "multi_chunk_transcript.json"
    artifact = TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="multi_test.mp4",
            format_name="mov,mp4",
            duration_seconds=100.0,
            size_bytes=1000000,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="faster-whisper",
            model="tiny",
            language="en",
            word_timestamps_enabled=True,
            duration_processed_seconds=100.0,
        ),
        word_timestamps_available=False,
        segment_count=3,
        total_words_count=35,
        segments=segments,
    )
    transcript_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")

    mock_multi_provider = MultiWindowMockProvider()
    monkeypatch.setattr("app.services.candidates.discovery.get_llm_provider", lambda **kwargs: mock_multi_provider)
    from app.core.config import get_settings
    fake_settings = get_settings().model_copy(update={"transcript_chunk_size": 15, "candidate_pool_target": 10})
    monkeypatch.setattr("app.services.candidates.discovery.get_settings", lambda: fake_settings)

    out_dir = tmp_path / "multi_candidates_out"
    saved_path = await run_candidate_discovery(
        transcript_path=transcript_path,
        output_dir=out_dir,
        editorial_goal=EditorialGoal.EDUCATION,
    )

    assert saved_path.exists()
    candidate_data = json.loads(saved_path.read_text(encoding="utf-8"))
    res_artifact = CandidateArtifact.model_validate(candidate_data)

    # 1. Verify target was passed to provider for each window
    assert len(received_targets) >= 2
    # target_count = max(3, ceil(10 / num_chunks) + 1)
    for tgt in received_targets:
        assert tgt is not None
        assert tgt >= 3

    # 2. Verify chunks_processed and total_raw_candidates
    assert res_artifact.generation.chunks_processed >= 2
    assert res_artifact.generation.total_raw_candidates == 4

    # 3. Verify deduplication: duplicate boundary candidate [30, 58] was suppressed
    # 4 raw candidates -> 1 was suppressed -> 3 survived
    assert res_artifact.candidates_count == 3
    hooks = [c.hook for c in res_artifact.candidates]
    assert "Duplicate boundary candidate W2 higher score" in hooks
    assert "Duplicate boundary candidate W1" not in hooks  # lower score duplicate suppressed
    assert "Window 1 moment" in hooks
    assert "Window 2 distinct moment" in hooks
    assert res_artifact.candidates[0].id == "cnd_001"
    assert res_artifact.candidates[1].id == "cnd_002"
    assert res_artifact.candidates[2].id == "cnd_003"
    assert res_artifact.candidates[0].overall_score >= res_artifact.candidates[1].overall_score
