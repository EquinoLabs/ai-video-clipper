"""Comprehensive unit and integration tests for Stage 3 Standalone Short-Clip Pipeline."""

import json
from pathlib import Path
import pytest

from app.domain.candidates.models import (
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    LLMCandidateEvaluation,
    ScoreBreakdown,
)
from app.domain.manifest.models import (
    ClipFiles,
    ClipMetadata,
    ManifestLongClipItem,
    RunManifest,
    SourceVideoReference,
)
from app.domain.rendering.models import RenderValidationResult
from app.domain.timeline.models import (
    ClipTimeline,
    TimelineBoundsError,
    parent_local_to_source,
    source_to_parent_local,
)
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.services.candidates.short_package import (
    LongMasterPackageError,
    validate_long_master_package,
)
from app.services.candidates.short_pipeline import run_short_clip_pipeline
from app.services.llm.base import LLMProvider
from app.services.rendering.short_clip_renderer import render_short_clip_package
from app.services.storage.output_manager import OutputManager
from app.services.transcription.slicing import (
    slice_transcript_for_long_clip,
    slice_transcript_for_short_clip,
)


@pytest.fixture
def mock_long_master_package(tmp_path: Path):
    """Create a fully valid long master package structure on disk."""
    long_dir = tmp_path / "run_20261024_01" / "long_clips" / "clip_01"
    long_dir.mkdir(parents=True, exist_ok=True)

    # 1. Clean master video (non-empty)
    clean_master = long_dir / "clip_01.mp4"
    clean_master.write_bytes(b"dummy mp4 video bytes")

    # 2. Sliced transcript (duration 45.0s, local coordinates 0.0s to 45.0s)
    segments = [
        TranscriptSegment(
            id=0,
            start_seconds=0.0,
            end_seconds=15.0,
            duration_seconds=15.0,
            text="So you know how we were talking about Devil Wears Prada trivia?",
            words=[
                WordTiming(word="So", start_seconds=0.0, end_seconds=0.4),
                WordTiming(word="trivia?", start_seconds=14.2, end_seconds=14.9),
            ],
        ),
        TranscriptSegment(
            id=1,
            start_seconds=15.0,
            end_seconds=30.0,
            duration_seconds=15.0,
            text="I was genuinely confused. Wait, that was me, but I'm the is it that's wild.",
            words=[
                WordTiming(word="I", start_seconds=15.0, end_seconds=15.3),
                WordTiming(word="wild.", start_seconds=29.1, end_seconds=29.8),
            ],
        ),
        TranscriptSegment(
            id=2,
            start_seconds=30.0,
            end_seconds=45.0,
            duration_seconds=15.0,
            text="And then everyone in the audience started laughing so hard.",
            words=[
                WordTiming(word="And", start_seconds=30.0, end_seconds=30.3),
                WordTiming(word="hard.", start_seconds=44.1, end_seconds=44.8),
            ],
        ),
    ]
    transcript = TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="lng_001.mp4",
            duration_seconds=45.0,
            format_name="mov,mp4",
            size_bytes=1000,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="whisper",
            model="base.en",
            duration_processed_seconds=45.0,
        ),
        word_timestamps_available=True,
        segment_count=3,
        total_words_count=18,
        warnings=[],
        segments=segments,
    )
    transcript_path = long_dir / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")

    # 3. metadata.json (source interval 80.0s to 125.0s, local 0.0s to 45.0s)
    timeline = ClipTimeline(
        source_start_seconds=80.0,
        source_end_seconds=125.0,
        local_start_seconds=0.0,
        local_end_seconds=45.0,
        duration_seconds=45.0,
    )
    metadata = ClipMetadata(
        clip_id="lng_001",
        clip_type="long",
        parent_id="vid_source_01",
        parent_type="source_video",
        source_video_id="vid_source_01",
        timeline=timeline,
        hook="Anne talks about Devil Wears Prada trivia",
        overall_score=89.0,
        status="clean_master_ready",
        files=ClipFiles(
            clean_master="clip_01.mp4",
            transcript="transcript.json",
        ),
    )
    meta_path = long_dir / "metadata.json"
    meta_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")

    return long_dir, long_dir.parent.parent


# -----------------------------------------------------------------------------
# 1. Input Package Validation Tests
# -----------------------------------------------------------------------------
def test_validate_long_master_package_success(mock_long_master_package):
    long_dir, _ = mock_long_master_package
    pkg = validate_long_master_package(long_dir)
    assert pkg.metadata.clip_id == "lng_001"
    assert pkg.metadata.clip_type == "long"
    assert pkg.clean_master_path.name == "clip_01.mp4"
    assert len(pkg.transcript.segments) == 3


def test_validate_long_master_package_missing_metadata(tmp_path: Path):
    d = tmp_path / "bad_pkg"
    d.mkdir()
    (d / "clip_01.mp4").write_bytes(b"content")
    (d / "transcript.json").write_text("{}", encoding="utf-8")
    with pytest.raises(LongMasterPackageError, match="Missing required 'metadata.json'"):
        validate_long_master_package(d)


def test_validate_long_master_package_rejects_recursive_shorts(mock_long_master_package):
    """Ensures short packages cannot be passed into short discovery (no recursive shorts)."""
    long_dir, _ = mock_long_master_package
    # Overwrite metadata to short
    meta_path = long_dir / "metadata.json"
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_data["clip_type"] = "short"
    meta_data["parent_type"] = "long_clip"
    meta_data["parent_id"] = "lng_parent"
    meta_path.write_text(json.dumps(meta_data), encoding="utf-8")

    with pytest.raises(LongMasterPackageError, match="Recursive short-of-short discovery is strictly prohibited"):
        validate_long_master_package(long_dir)


def test_validate_long_master_package_empty_master(mock_long_master_package):
    long_dir, _ = mock_long_master_package
    (long_dir / "clip_01.mp4").write_bytes(b"")  # 0 bytes
    with pytest.raises(LongMasterPackageError, match="is empty"):
        validate_long_master_package(long_dir)


# -----------------------------------------------------------------------------
# 2. Timeline Conversions and Slicing Tests
# -----------------------------------------------------------------------------
def test_short_timeline_conversions():
    # Long clip starts at source 80.0s, ends at source 125.0s (duration 45.0s)
    # Short moment inside long clip starts at local 10.0s, ends at local 35.0s (duration 25.0s)
    parent_source_start = 80.0
    parent_local_start = 10.0
    parent_local_end = 35.0

    src_start = parent_local_to_source(parent_local_start, parent_source_start)
    src_end = parent_local_to_source(parent_local_end, parent_source_start)
    assert src_start == 90.0
    assert src_end == 115.0

    # Back to parent-local
    assert source_to_parent_local(src_start, parent_source_start) == 10.0
    assert source_to_parent_local(src_end, parent_source_start) == 35.0


def test_short_transcript_slicing(mock_long_master_package):
    long_dir, _ = mock_long_master_package
    pkg = validate_long_master_package(long_dir)

    # Slice short moment: local 15.0s to 30.0s (segment 1)
    sliced_short = slice_transcript_for_short_clip(
        long_transcript=pkg.transcript,
        short_local_start_seconds=15.0,
        short_local_end_seconds=30.0,
        clip_id="srt_001",
    )

    assert round(sliced_short.source_media.duration_seconds, 2) == 15.0
    assert len(sliced_short.segments) == 1
    seg = sliced_short.segments[0]
    assert seg.start_seconds == 0.0
    assert seg.end_seconds == 15.0
    assert seg.words[0].word == "I"
    assert seg.words[0].start_seconds == 0.0
    assert seg.words[-1].word == "wild."
    assert seg.words[-1].end_seconds <= 15.0


# -----------------------------------------------------------------------------
# 3. Short Clip Rendering Packaging & Lineage Tests
# -----------------------------------------------------------------------------
def test_render_short_clip_package_flow(mock_long_master_package, monkeypatch):
    long_dir, run_dir = mock_long_master_package
    pkg = validate_long_master_package(long_dir)
    mgr = OutputManager(output_root=run_dir.parent)

    # Mock FFmpeg render
    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"short mp4 bytes")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=50,
            duration_seconds=kwargs.get("candidate_end_seconds", 0) - kwargs.get("candidate_start_seconds", 0),
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    short_meta, manifest_item = render_short_clip_package(
        parent_clean_master_path=pkg.clean_master_path,
        parent_transcript=pkg.transcript,
        parent_metadata=pkg.metadata,
        clip_id="srt_001_01",
        clip_index=1,
        parent_local_start_seconds=15.0,
        parent_local_end_seconds=35.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=False,
        hook="Funny amnesia joke",
        score=92.0,
    )

    # Verify short directory and files
    short_dir = mgr.get_short_clip_dir(run_dir, "srt_001_01")
    assert (short_dir / "srt_001_01.mp4").exists()
    assert (short_dir / "transcript.json").exists()
    assert (short_dir / "metadata.json").exists()

    # Lineage and timing verification
    assert short_meta.clip_type == "short"
    assert short_meta.parent_type == "long_clip"
    assert short_meta.parent_id == "lng_001"
    assert short_meta.source_video_id == "vid_source_01"
    assert short_meta.timeline.source_start_seconds == 95.0
    assert short_meta.timeline.source_end_seconds == 115.0
    assert short_meta.timeline.local_start_seconds == 15.0
    assert short_meta.timeline.local_end_seconds == 35.0
    assert short_meta.timeline.duration_seconds == 20.0

    # Manifest item
    assert manifest_item.clip_id == "srt_001_01"
    assert manifest_item.parent_clip_id == "lng_001"
    assert manifest_item.duration_seconds == 20.0
    assert manifest_item.parent_local_start_seconds == 15.0


# -----------------------------------------------------------------------------
# 4. Standalone Short-Clip Pipeline End-to-End Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_short_clip_pipeline_with_candidates(mock_long_master_package, monkeypatch):
    long_dir, run_dir = mock_long_master_package
    mgr = OutputManager(output_root=run_dir.parent)

    # Create run manifest in run_dir to test manifest update
    manifest = RunManifest(
        run_id="run_20261024_01",
        source_video=SourceVideoReference(
            video_id="vid_source_01",
            normalized_name="anne_interview",
            source_path="inputs/anne.mp4",
            duration_seconds=500.0,
        ),
        long_clips=[
            ManifestLongClipItem(
                clip_id="lng_001",
                folder="long_clips/clip_01",
                source_start_seconds=80.0,
                source_end_seconds=125.0,
                duration_seconds=45.0,
                score=89.0,
                status="clean_master_ready",
                clean_master_path="long_clips/clip_01/clip_01.mp4",
                short_clips_count=0,
            )
        ],
    )
    mgr.save_manifest(run_dir, manifest)

    # Mock LLM provider that returns one short candidate in parent-local coordinates (15.0s to 30.0s)
    prompt_record = []

    class MockShortProvider(LLMProvider):
        async def discover_and_evaluate(self, transcript_segments, editorial_goal, settings, custom_instructions=None, target_count=None, is_long_clip=False):
            prompt_record.append(is_long_clip)
            return [
                LLMCandidateEvaluation(
                    start_seconds=15.0,
                    end_seconds=30.0,
                    hook="Wait that was me amnesia punchline",
                    transcript_excerpt="I was genuinely confused. Wait, that was me, but I'm the is it that's wild.",
                    score_dimensions=ScoreBreakdown(
                        hook_strength=4.5,
                        completeness_coherence=4.5,
                        standalone_understandability=4.5,
                        goal_relevance=4.5,
                        goal_specific_impact=4.5,
                        specificity_insight=4.0,
                        pacing_conciseness=4.5,
                        ending_quality=4.5,
                    ),
                    rationale="Great short punchline",
                    evidence=[
                        EvidenceItem(start_seconds=15.0, end_seconds=20.0, quote="I was genuinely confused."),
                    ],
                    confidence_label=ConfidenceLabel.HIGH,
                )
            ]

    # Mock FFmpeg rendering
    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"short mp4 bytes")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=50,
            duration_seconds=kwargs.get("candidate_end_seconds", 0) - kwargs.get("candidate_start_seconds", 0),
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    res = await run_short_clip_pipeline(
        long_clip_dir=long_dir,
        output_run_dir=run_dir,
        provider=MockShortProvider(),
        render_clean_masters=True,
    )

    # 1. Assert short-mode prompt was called (is_long_clip=False)
    assert prompt_record == [False]
    assert res.candidates_count == 1
    assert res.rendered_count == 1

    # 2. Assert short artifacts exist
    assert (long_dir / "short_candidates.json").exists()
    assert len(res.manifest_items) == 1
    short_id = res.manifest_items[0].clip_id
    assert (run_dir / "short_clips" / short_id / f"{short_id}.mp4").exists()
    assert (run_dir / "short_clips" / short_id / "metadata.json").exists()

    # 3. Assert RunManifest was updated
    updated_manifest = mgr.load_manifest(run_dir)
    assert len(updated_manifest.short_clips) == 1
    assert updated_manifest.short_clips[0].parent_clip_id == "lng_001"
    assert updated_manifest.long_clips[0].short_clips_count == 1


@pytest.mark.asyncio
async def test_run_short_clip_pipeline_valid_zero_shorts(mock_long_master_package):
    """Zero shorts is a valid and expected result when no candidate meets quality criteria."""
    long_dir, run_dir = mock_long_master_package

    class MockEmptyProvider(LLMProvider):
        async def discover_and_evaluate(self, transcript_segments, editorial_goal, settings, custom_instructions=None, target_count=None, is_long_clip=False):
            return []

    res = await run_short_clip_pipeline(
        long_clip_dir=long_dir,
        output_run_dir=run_dir,
        provider=MockEmptyProvider(),
        render_clean_masters=True,
    )

    assert res.candidates_count == 0
    assert res.rendered_count == 0
    assert (long_dir / "short_candidates.json").exists()
    cand_data = json.loads((long_dir / "short_candidates.json").read_text(encoding="utf-8"))
    assert cand_data["candidates_count"] == 0
