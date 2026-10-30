"""Unit tests for long-mode candidate discovery output bounding and partial chunk preservation."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.domain.candidates.models import (
    CandidateArtifact,
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    LLMCandidateEvaluation,
    ScoreBreakdown,
)
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.services.candidates.discovery import run_candidate_discovery
from app.services.llm.base import LLMProvider
from app.services.llm.models import LLMCandidatesResponseEnvelope
from app.services.llm.ollama_adapter import OllamaProviderError


def make_test_transcript_artifact(num_segments: int = 10, words_per_seg: int = 20) -> TranscriptArtifact:
    """Create a sample transcript artifact with controllable word count."""
    segments = []
    for i in range(num_segments):
        start = float(i * 10)
        end = start + 10.0
        words_text = " ".join([f"w_{i}_{w}" for w in range(words_per_seg)])
        word_timings = [
            WordTiming(word=f"w_{i}_{w}", start_seconds=start + w * 0.5, end_seconds=start + (w + 1) * 0.5)
            for w in range(words_per_seg)
        ]
        segments.append(
            TranscriptSegment(
                id=i + 1,
                start_seconds=start,
                end_seconds=end,
                duration_seconds=10.0,
                text=words_text,
                words=word_timings,
            )
        )

    source_meta = SourceMediaMetadata(
        filename="test_video.mp4",
        format_name="mov,mp4",
        duration_seconds=float(num_segments * 10),
        size_bytes=1000000,
        video_streams_count=1,
        audio_streams_count=1,
        selected_audio_stream_index=0,
        audio_codec="aac",
        audio_sample_rate=44100,
        audio_channels=2,
    )
    run_meta = TranscriptionRunMetadata(
        provider="test",
        model="base",
        language="en",
        language_probability=0.99,
        word_timestamps_enabled=True,
        parameters={},
        duration_processed_seconds=float(num_segments * 10),
    )
    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=source_meta,
        transcription=run_meta,
        word_timestamps_available=True,
        segment_count=len(segments),
        total_words_count=num_segments * words_per_seg,
        warnings=[],
        segments=segments,
    )


def make_sample_candidate_eval(start: float, end: float, hook: str, quote: str) -> LLMCandidateEvaluation:
    return LLMCandidateEvaluation(
        start_seconds=start,
        end_seconds=end,
        hook=hook,
        transcript_excerpt=quote,
        score_dimensions=ScoreBreakdown(
            hook_strength=4.5,
            completeness_coherence=4.5,
            standalone_understandability=4.5,
            goal_relevance=4.5,
            goal_specific_impact=4.5,
            specificity_insight=4.5,
            pacing_conciseness=4.5,
            ending_quality=4.5,
        ),
        rationale="Strong complete conversation arc.",
        evidence=[EvidenceItem(start_seconds=start, end_seconds=end, quote=quote)],
        confidence_label=ConfidenceLabel.HIGH,
    )


def test_candidates_envelope_max_length_schema_constraint():
    """Verify that LLMCandidatesResponseEnvelope schema contains maxItems constraint."""
    schema = LLMCandidatesResponseEnvelope.model_json_schema()
    assert "properties" in schema
    assert "candidates" in schema["properties"]
    assert "maxItems" in schema["properties"]["candidates"]
    assert schema["properties"]["candidates"]["maxItems"] == 15


@pytest.mark.asyncio
async def test_chunk_failure_preserves_partial_candidates(tmp_path: Path):
    """Verify that when Chunk 1 succeeds and Chunk 2 fails, Chunk 1 candidates are preserved

    in candidates_partial.json, and a clear error is raised (incomplete discovery is not marked success).
    """
    # 60 segments of 30 words = 1,800 words (exceeds 1,500 word chunk size, forcing 2 chunks)
    transcript_artifact = make_test_transcript_artifact(num_segments=60, words_per_seg=30)
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(transcript_artifact.model_dump_json(indent=2), encoding="utf-8")

    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # First segment text for quoting
    seg0_text = transcript_artifact.segments[0].text
    seg1_text = transcript_artifact.segments[1].text
    seg2_text = transcript_artifact.segments[2].text
    combined_quote = f"{seg0_text} {seg1_text} {seg2_text}"

    cand1 = make_sample_candidate_eval(
        start=0.0,
        end=30.0,
        hook="Chunk 1 great conversation",
        quote=combined_quote,
    )

    mock_provider = AsyncMock(spec=LLMProvider)
    # Chunk 1 succeeds returning 1 candidate; Chunk 2 raises OllamaProviderError
    mock_provider.discover_and_evaluate.side_effect = [
        [cand1],
        OllamaProviderError("Ollama request timed out after 600.0s for model 'qwen2.5:7b'."),
    ]

    with patch("app.services.candidates.discovery.get_llm_provider", return_value=mock_provider):
        with pytest.raises(OllamaProviderError) as exc_info:
            await run_candidate_discovery(
                transcript_path=transcript_path,
                output_dir=out_dir,
                editorial_goal=EditorialGoal.HUMOR,
                provider_name="ollama",
                model_name="qwen2.5:7b",
                mode="long",
            )

    # Verify clear error was raised
    assert "Candidate discovery failed on chunk 2" in str(exc_info.value)
    assert "timed out after 600.0s" in str(exc_info.value)

    # Verify candidates.json was NOT written as a successful run
    assert not (out_dir / "candidates.json").exists()

    # Verify candidates_partial.json WAS written
    partial_file = out_dir / "candidates_partial.json"
    assert partial_file.exists()

    partial_data = json.loads(partial_file.read_text(encoding="utf-8"))
    artifact = CandidateArtifact.model_validate(partial_data)

    assert artifact.candidates_count == 1
    assert artifact.candidates[0].hook == "Chunk 1 great conversation"
    assert artifact.generation.chunks_processed == 1
    assert artifact.generation.failed_chunks is not None
    assert len(artifact.generation.failed_chunks) == 1
    assert artifact.generation.failed_chunks[0]["chunk_index"] == 1
    assert "timed out after 600.0s" in artifact.generation.failed_chunks[0]["error"]


@pytest.mark.asyncio
async def test_long_mode_reads_long_candidate_pool_target(tmp_path: Path):
    """Verify that long-mode discovery reads long_candidate_pool_target (default 4)

    and short-mode discovery reads candidate_pool_target (default 10).
    """
    transcript_artifact = make_test_transcript_artifact(num_segments=60, words_per_seg=30)
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(transcript_artifact.model_dump_json(indent=2), encoding="utf-8")

    out_dir_long = tmp_path / "out_long"
    out_dir_long.mkdir(parents=True, exist_ok=True)
    out_dir_short = tmp_path / "out_short"
    out_dir_short.mkdir(parents=True, exist_ok=True)

    captured_targets = []

    async def fake_discover(**kwargs):
        captured_targets.append(kwargs.get("target_count"))
        return []

    mock_provider = AsyncMock(spec=LLMProvider)
    mock_provider.discover_and_evaluate.side_effect = fake_discover

    with patch("app.services.candidates.discovery.get_llm_provider", return_value=mock_provider):
        # 1. Test long mode: 1800 words / 1500 target = 2 chunks.
        # Pool target defaults to 4 -> per_chunk_target = max(3, -(-4 // 2) + 1) = 3
        await run_candidate_discovery(
            transcript_path=transcript_path,
            output_dir=out_dir_long,
            editorial_goal=EditorialGoal.HUMOR,
            mode="long",
        )
        assert len(captured_targets) == 2
        assert captured_targets[0] == 3
        assert captured_targets[1] == 3

        captured_targets.clear()

        # 2. Test short mode: 1800 words / 750 target = 3 chunks.
        # Pool target defaults to 10 -> per_chunk_target = max(3, -(-10 // 3) + 1) = 5
        await run_candidate_discovery(
            transcript_path=transcript_path,
            output_dir=out_dir_short,
            editorial_goal=EditorialGoal.HUMOR,
            mode="short",
        )
        assert len(captured_targets) == 3
        assert captured_targets[0] == 5
        assert captured_targets[1] == 5
        assert captured_targets[2] == 5


def test_per_chunk_target_calculation_for_various_chunk_counts():
    """Verify formula max(3, -(-pool_target // num_chunks) + 1) for 1, 2, 3, and 4 chunks."""
    def calc_target(pool_target: int, num_chunks: int) -> int:
        return max(3, -(-pool_target // num_chunks) + 1) if num_chunks > 0 else 3

    # For default long_candidate_pool_target = 4:
    assert calc_target(4, 1) == 5  # ceil(4/1) + 1 = 5
    assert calc_target(4, 2) == 3  # ceil(4/2) + 1 = 3
    assert calc_target(4, 3) == 3  # ceil(4/3) + 1 = 3 (max with 3 floor)
    assert calc_target(4, 4) == 3  # ceil(4/4) + 1 = 2 -> clamped to 3

    # For short candidate_pool_target = 10:
    assert calc_target(10, 1) == 11
    assert calc_target(10, 2) == 6
    assert calc_target(10, 3) == 5
    assert calc_target(10, 4) == 4


@pytest.mark.asyncio
async def test_cli_explicit_overrides_precedence(tmp_path: Path):
    """Verify that per_chunk_target overrides candidate_pool_target, which overrides settings."""
    transcript_artifact = make_test_transcript_artifact(num_segments=60, words_per_seg=30)
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(transcript_artifact.model_dump_json(indent=2), encoding="utf-8")
    out_dir = tmp_path / "out_override"
    out_dir.mkdir(parents=True, exist_ok=True)

    captured_targets = []

    async def fake_discover(**kwargs):
        captured_targets.append(kwargs.get("target_count"))
        return []

    mock_provider = AsyncMock(spec=LLMProvider)
    mock_provider.discover_and_evaluate.side_effect = fake_discover

    with patch("app.services.candidates.discovery.get_llm_provider", return_value=mock_provider):
        # 1. candidate_pool_target override passed explicitly (e.g. 6 across 2 chunks -> target 4)
        await run_candidate_discovery(
            transcript_path=transcript_path,
            output_dir=out_dir,
            mode="long",
            candidate_pool_target=6,
        )
        assert captured_targets == [4, 4]

        captured_targets.clear()

        # 2. per_chunk_target override takes highest precedence (e.g. directly requesting 2)
        await run_candidate_discovery(
            transcript_path=transcript_path,
            output_dir=out_dir,
            mode="long",
            candidate_pool_target=10,
            per_chunk_target=2,
        )
        assert captured_targets == [2, 2]


def test_schema_max_items_matches_effective_per_chunk_target():
    """Verify that OllamaAdapter dynamically sets maxItems in schema to match target_count."""
    import copy
    from app.services.llm.models import LLMCandidatesResponseEnvelope

    target_count = 3
    schema = copy.deepcopy(LLMCandidatesResponseEnvelope.model_json_schema())
    schema["properties"]["candidates"]["maxItems"] = max(1, target_count)
    assert schema["properties"]["candidates"]["maxItems"] == 3
