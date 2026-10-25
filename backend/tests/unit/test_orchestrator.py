"""Unit tests for Stage 4 Pipeline Orchestration."""

import json
from pathlib import Path
import pytest

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.ai_clipper.domain.manifest.models import ManifestLongClipItem, ManifestShortClipItem, RunManifest
from app.common.media.probing import AudioStreamInfo, MediaProbeResult, VideoStreamInfo
from app.ai_clipper.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.ai_clipper.services.pipeline.orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    run_pipeline_orchestrator,
)
from app.ai_clipper.services.storage.output_manager import OutputManager


@pytest.fixture
def mock_probe_result(tmp_path: Path) -> MediaProbeResult:
    return MediaProbeResult(
        format_name="mov,mp4,m4a",
        duration_seconds=50.0,
        size_bytes=1000,
        video_streams=[
            VideoStreamInfo(
                index=0,
                codec_name="h264",
                width=1920,
                height=1080,
                duration_seconds=50.0,
            )
        ],
        audio_streams=[
            AudioStreamInfo(
                index=0,
                stream_index=1,
                codec_name="aac",
                sample_rate=44100,
                channels=2,
                duration_seconds=50.0,
            )
        ],
        selected_audio_stream_index=0,
        selected_audio_stream_id=1,
    )


@pytest.fixture
def sample_transcript(tmp_path: Path) -> TranscriptArtifact:
    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="source.mp4",
            format_name="mov,mp4",
            duration_seconds=50.0,
            size_bytes=1000,
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
            duration_processed_seconds=50.0,
        ),
        word_timestamps_available=True,
        segment_count=2,
        total_words_count=10,
        segments=[
            TranscriptSegment(
                id=0,
                start_seconds=0.0,
                end_seconds=20.0,
                duration_seconds=20.0,
                text="First segment of the conversation.",
                words=[WordTiming(word="First", start_seconds=0.0, end_seconds=1.0)],
            ),
            TranscriptSegment(
                id=1,
                start_seconds=20.0,
                end_seconds=45.0,
                duration_seconds=25.0,
                text="Second segment with the punchline.",
                words=[WordTiming(word="Second", start_seconds=20.0, end_seconds=21.0)],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_orchestrator_successful_flow_with_reused_transcript(
    tmp_path: Path, mock_probe_result, sample_transcript, monkeypatch
):
    source_video = tmp_path / "test_video.mp4"
    source_video.write_bytes(b"dummy video data")

    transcript_path = tmp_path / "existing_transcript.json"
    transcript_path.write_text(sample_transcript.model_dump_json(indent=2), encoding="utf-8")

    out_root = tmp_path / "outputs"
    mgr = OutputManager(output_root=out_root)

    # Mock probe
    monkeypatch.setattr("app.ai_clipper.services.pipeline.orchestrator.probe_media_file", lambda p: mock_probe_result)

    # Mock discover_and_render_long_clips
    async def mock_long_clips(*args, **kwargs):
        run_dir = kwargs["run_dir"]
        long_dir = run_dir / "long_clips" / "clip_01"
        long_dir.mkdir(parents=True, exist_ok=True)
        # Create dummy long package files so short pipeline validator sees them
        (long_dir / "clip_01.mp4").write_text("clean master")
        (long_dir / "transcript.json").write_text(sample_transcript.model_dump_json())
        metadata_dict = {
            "schema_version": "v1.0",
            "clip_id": "lng_001",
            "clip_type": "long",
            "parent_id": kwargs["source_video_id"],
            "parent_type": "source_video",
            "source_video_id": kwargs["source_video_id"],
            "timeline": {
                "source_start_seconds": 0.0,
                "source_end_seconds": 45.0,
                "local_start_seconds": 0.0,
                "local_end_seconds": 45.0,
                "duration_seconds": 45.0,
            },
            "status": "clean_master_ready",
            "files": {"clean_master": "clip_01.mp4", "transcript": "transcript.json"},
        }
        (long_dir / "metadata.json").write_text(json.dumps(metadata_dict))

        return [
            ManifestLongClipItem(
                clip_id="lng_001",
                folder="long_clips/clip_01",
                source_start_seconds=0.0,
                source_end_seconds=45.0,
                duration_seconds=45.0,
                status="clean_master_ready",
                clean_master_path="long_clips/clip_01/clip_01.mp4",
                short_clips_count=1,
            )
        ]

    monkeypatch.setattr(
        "app.ai_clipper.services.pipeline.orchestrator.discover_and_render_long_clips",
        mock_long_clips,
    )

    # Mock run_short_clip_pipeline
    from app.ai_clipper.services.candidates.short_pipeline import ShortPipelineResult
    from app.ai_clipper.services.candidates.short_package import validate_long_master_package
    from app.ai_clipper.domain.candidates.models import CandidateArtifact, CandidateGenerationMetadata
    from app.ai_clipper.domain.candidates.models import GenerationSettings

    async def mock_short_pipeline(*args, **kwargs):
        long_dir = kwargs["long_clip_dir"]
        pkg = validate_long_master_package(long_dir)
        short_manifest_item = ManifestShortClipItem(
            clip_id="srt_001_01",
            parent_clip_id=pkg.metadata.clip_id,
            folder="short_clips/clip_01",
            source_start_seconds=10.0,
            source_end_seconds=25.0,
            parent_local_start_seconds=10.0,
            parent_local_end_seconds=25.0,
            duration_seconds=15.0,
            status="clean_master_ready",
        )
        cand_artifact = CandidateArtifact(
            schema_version="v1.0",
            source_media=sample_transcript.source_media,
            generation=CandidateGenerationMetadata(
                editorial_goal=EditorialGoal.HUMOR,
                provider="mock",
                model="mock",
                settings=GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0),
                scoring_version="v1.0",
                chunks_processed=1,
                total_raw_candidates=1,
            ),
            candidates_count=1,
            candidates=[],
        )
        return ShortPipelineResult(
            long_master_package=pkg,
            candidate_artifact=cand_artifact,
            rendered_shorts=[],
            manifest_items=[short_manifest_item],
            candidates_count=1,
            rendered_count=1,
        )

    monkeypatch.setattr(
        "app.ai_clipper.services.pipeline.orchestrator.run_short_clip_pipeline",
        mock_short_pipeline,
    )

    # Execute orchestrator
    result: OrchestratorResult = await run_pipeline_orchestrator(
        source_video_path=source_video,
        config=OrchestratorConfig(pipeline_mode="full", editorial_goal=EditorialGoal.HUMOR),
        existing_transcript_path=transcript_path,
        output_manager=mgr,
    )

    # Assertions
    assert result.status == "completed"
    assert result.long_clips_count == 1
    assert result.short_clips_count == 1
    assert result.stage_statuses["transcription"] == "completed"
    assert result.stage_statuses["long_discovery"] == "completed"
    assert result.stage_statuses["short_discovery"] == "completed"
    assert Path(result.manifest_path).exists()

    # Verify manifest JSON on disk
    manifest_data = json.loads(Path(result.manifest_path).read_text())
    manifest = RunManifest.model_validate(manifest_data)
    assert manifest.status == "completed"
    assert len(manifest.long_clips) == 1
    assert len(manifest.short_clips) == 1
    assert manifest.short_clips[0].parent_clip_id == "lng_001"


@pytest.mark.asyncio
async def test_orchestrator_valid_zero_long_clips(
    tmp_path: Path, mock_probe_result, sample_transcript, monkeypatch
):
    source_video = tmp_path / "test_video.mp4"
    source_video.write_bytes(b"dummy video data")

    transcript_path = tmp_path / "existing_transcript.json"
    transcript_path.write_text(sample_transcript.model_dump_json(indent=2), encoding="utf-8")

    out_root = tmp_path / "outputs"
    mgr = OutputManager(output_root=out_root)

    monkeypatch.setattr("app.ai_clipper.services.pipeline.orchestrator.probe_media_file", lambda p: mock_probe_result)

    # Mock long discovery returning 0 long clips (valid empty discovery)
    async def mock_zero_long_clips(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.ai_clipper.services.pipeline.orchestrator.discover_and_render_long_clips",
        mock_zero_long_clips,
    )

    result = await run_pipeline_orchestrator(
        source_video_path=source_video,
        config=OrchestratorConfig(pipeline_mode="full"),
        existing_transcript_path=transcript_path,
        output_manager=mgr,
    )

    assert result.status == "completed"
    assert result.long_clips_count == 0
    assert result.short_clips_count == 0
    assert result.stage_statuses["long_discovery"] == "completed"
    assert result.stage_statuses["short_discovery"] == "completed"


@pytest.mark.asyncio
async def test_orchestrator_fails_on_missing_source(tmp_path: Path):
    missing_video = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        await run_pipeline_orchestrator(source_video_path=missing_video)


@pytest.mark.asyncio
async def test_orchestrator_stage_failure_marks_active_stage_as_failed(
    tmp_path: Path, mock_probe_result, sample_transcript, monkeypatch
):
    source_video = tmp_path / "failing_video.mp4"
    source_video.write_bytes(b"dummy video data")

    transcript_path = tmp_path / "existing_transcript.json"
    transcript_path.write_text(sample_transcript.model_dump_json(indent=2), encoding="utf-8")

    out_root = tmp_path / "outputs"
    mgr = OutputManager(output_root=out_root)

    monkeypatch.setattr("app.ai_clipper.services.pipeline.orchestrator.probe_media_file", lambda p: mock_probe_result)

    # Mock long discovery raising an exception (e.g. OpenAIProviderError)
    async def mock_failing_long_clips(*args, **kwargs):
        raise RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY in environment or .env.")

    monkeypatch.setattr(
        "app.ai_clipper.services.pipeline.orchestrator.discover_and_render_long_clips",
        mock_failing_long_clips,
    )

    result = await run_pipeline_orchestrator(
        source_video_path=source_video,
        config=OrchestratorConfig(pipeline_mode="full"),
        existing_transcript_path=transcript_path,
        output_manager=mgr,
    )

    assert result.status == "failed"
    assert result.stage_statuses["transcription"] == "completed"
    assert result.stage_statuses["long_discovery"] == "failed"
    assert result.stage_statuses["short_discovery"] == "pending"
    assert len(result.errors) == 1
    assert "OpenAI API key not configured" in result.errors[0]

    # Verify manifest on disk also has stage_statuses["long_discovery"] == "failed"
    manifest_disk = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest_disk["status"] == "failed"
    assert manifest_disk["stage_statuses"]["long_discovery"] == "failed"
    assert manifest_disk["stage_statuses"]["short_discovery"] == "pending"
