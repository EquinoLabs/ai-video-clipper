"""Unit test suite for pipeline source selection and date-scoped input ingestion.

Verifies:
1. Single-video selection discovers source in init_input/.
2. Selected-video mode processes only requested videos.
3. All-video mode processes all eligible source videos.
4. Video previously ingested on Oct 29 is copied into Oct 31's intake when selected on Oct 31.
5. Re-running on Oct 31 reuses the valid Oct 31 intake copy.
6. Reusing today's intake does not change its metadata timestamp or duplicate files.
7. Both date folders retain the same canonical source UUID.
8. Incomplete or invalid today's intake is detected and repaired.
9. Missing or invalid source files produce clear errors.
10. No mode accidentally selects a video from an older input/ folder.
11. Long and short artifacts retain the correct source UUID.
12. Existing historical run discovery and media access still work.
"""

import datetime
import json
import uuid
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from app.domain.ingestion.models import IngestionMetadata
from app.services.media.probing import AudioStreamInfo, MediaProbeResult, VideoStreamInfo
from app.services.storage.ingestion import compute_file_sha256, generate_stable_video_id
from app.services.storage.output_manager import OutputManager
from app.services.storage.staging import (
    find_date_scoped_intake_record,
    is_supported_video_file,
    materialize_intake_video,
    resolve_source_videos,
    stage_input_video,
)
from app.services.rendering.long_clip_renderer import render_long_clip_package
from app.services.rendering.short_clip_renderer import render_short_clip_package
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.domain.manifest.models import ClipMetadata, ManifestLongClipItem, ManifestShortClipItem
from app.domain.rendering.models import RenderValidationResult
from app.domain.timeline.models import ClipTimeline
from app.services.candidates.short_pipeline import ShortPipelineResult
from app.services.pipeline.batch_runner import process_batch_items
from app.main import app


@pytest.fixture
def mock_video_probe() -> MediaProbeResult:
    return MediaProbeResult(
        format_name="mov,mp4,m4a",
        duration_seconds=45.0,
        size_bytes=6000,
        video_streams=[
            VideoStreamInfo(
                index=0,
                codec_name="h264",
                width=1920,
                height=1080,
                duration_seconds=45.0,
            )
        ],
        audio_streams=[
            AudioStreamInfo(
                index=0,
                stream_index=1,
                codec_name="aac",
                sample_rate=44100,
                channels=2,
                duration_seconds=45.0,
            )
        ],
        selected_audio_stream_index=0,
        selected_audio_stream_id=1,
    )


@pytest.fixture
def sample_transcript() -> TranscriptArtifact:
    return TranscriptArtifact(
        schema_version="v1.0",
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_media=SourceMediaMetadata(
            filename="sample.mp4",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            duration_seconds=60.0,
            size_bytes=5000000,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=44100,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="faster-whisper",
            model="small",
            word_timestamps_enabled=True,
            duration_processed_seconds=60.0,
            device="cpu",
            compute_type="int8",
        ),
        word_timestamps_available=True,
        segment_count=2,
        segments=[
            TranscriptSegment(
                id=0,
                seek=0,
                start_seconds=0.0,
                end_seconds=30.0,
                duration_seconds=30.0,
                text="First segment of the conversation.",
                words=[
                    WordTiming(word="First", start_seconds=0.0, end_seconds=5.0),
                    WordTiming(word="segment", start_seconds=5.0, end_seconds=10.0),
                    WordTiming(word="conversation", start_seconds=10.0, end_seconds=30.0),
                ],
            ),
            TranscriptSegment(
                id=1,
                seek=3000,
                start_seconds=30.0,
                end_seconds=60.0,
                duration_seconds=30.0,
                text="Second segment with the punchline.",
                words=[
                    WordTiming(word="Second", start_seconds=30.0, end_seconds=35.0),
                    WordTiming(word="segment", start_seconds=35.0, end_seconds=45.0),
                    WordTiming(word="punchline", start_seconds=45.0, end_seconds=60.0),
                ],
            ),
        ],
    )


def test_1_single_video_selection_discovers_source_in_init_input(tmp_path: Path):
    """1. Single-video selection discovers the source in init_input/."""
    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    target_video = init_dir / "Anne Hathaway Interview.mp4"
    target_video.write_bytes(b"video bytes")

    # Mode 'single' by bare filename
    res1 = resolve_source_videos(init_input_dir=init_dir, mode="single", single="Anne Hathaway Interview.mp4")
    assert len(res1) == 1
    assert res1[0] == target_video.resolve()

    # Mode 'single' by relative path
    res2 = resolve_source_videos(init_input_dir=init_dir, mode="single", single="init_input/Anne Hathaway Interview.mp4")
    assert len(res2) == 1
    assert res2[0] == target_video.resolve()


def test_2_selected_video_mode_processes_only_requested_videos(tmp_path: Path):
    """2. Selected-video mode processes only the requested videos."""
    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    v1 = init_dir / "vid1.mp4"
    v2 = init_dir / "vid2.mp4"
    v3 = init_dir / "vid3.mp4"
    v1.write_bytes(b"1")
    v2.write_bytes(b"2")
    v3.write_bytes(b"3")

    selected = resolve_source_videos(
        init_input_dir=init_dir,
        mode="selected",
        selected=["vid1.mp4", "vid3.mp4"],
    )
    assert len(selected) == 2
    assert v1.resolve() in selected
    assert v3.resolve() in selected
    assert v2.resolve() not in selected


def test_3_all_video_mode_processes_all_eligible_source_videos(tmp_path: Path):
    """3. All-video mode processes all eligible source videos and ignores non-videos."""
    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    (init_dir / "vid1.mp4").write_bytes(b"1")
    (init_dir / "vid2.mov").write_bytes(b"2")
    (init_dir / "notes.txt").write_text("not a video")
    (init_dir / "metadata.json").write_text("{}")
    
    sub = init_dir / "nested"
    sub.mkdir()
    (sub / "vid3.mkv").write_bytes(b"3")

    all_vids = resolve_source_videos(init_input_dir=init_dir, mode="all")
    assert len(all_vids) == 3
    names = [v.name for v in all_vids]
    assert "vid1.mp4" in names
    assert "vid2.mov" in names
    assert "vid3.mkv" in names
    assert "notes.txt" not in names


def test_4_cross_date_materialization_copies_video_for_new_date(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """4. A video previously ingested on Oct 29 is copied into Oct 31's intake when selected on Oct 31."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    source_file = init_dir / "Show Interview.mp4"
    source_bytes = b"authoritative show bytes 98765"
    source_file.write_bytes(source_bytes)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Prepopulate historical Oct 29 intake copy
    hash_val = compute_file_sha256(source_file)
    source_uuid = generate_stable_video_id(hash_val)

    oct29_dir = input_dir / "2026-10-29" / source_uuid
    oct29_dir.mkdir(parents=True)
    oct29_video = oct29_dir / "show_interview.mp4"
    oct29_video.write_bytes(source_bytes)
    (oct29_dir / "metadata.json").write_text(
        json.dumps({
            "schema_version": "v1.0",
            "video_id": source_uuid,
            "source_video_id": source_uuid,
            "original_filename": "Show Interview.mp4",
            "stored_filename": "show_interview.mp4",
            "ingested_at": "2026-10-29T08:00:00+05:30",
            "ingestion_date": "2026-10-29",
            "file_size_bytes": len(source_bytes),
            "media_type": "mp4",
            "content_sha256": hash_val,
            "source_path": str(oct29_video),
            "probe_status": "probed",
        })
    )

    # Now select and materialize on October 31
    res31 = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )

    assert res31.is_staged is True
    # Oct 31 intake copy exists under 2026-10-31
    assert res31.staged_path.exists()
    assert "2026-10-31" in str(res31.staged_path)
    assert res31.staged_path.parent.name == source_uuid
    assert res31.staged_path != oct29_video
    # Historical Oct 29 intake copy remains completely intact
    assert oct29_video.exists()


def test_5_same_date_rerun_reuses_valid_intake_copy(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """5. Re-running on October 31 reuses the valid October 31 intake copy."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    source_file = init_dir / "Comedy Sketch.mp4"
    source_file.write_bytes(b"comedy sketch raw bytes")

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # First run on Oct 31
    res_run1 = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )
    assert res_run1.is_staged is True

    # Second run on Oct 31 with same source
    res_run2 = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )
    assert res_run2.is_staged is True
    assert res_run2.staged_path == res_run1.staged_path
    assert res_run2.metadata.video_id == res_run1.metadata.video_id


def test_6_intake_reuse_preserves_timestamp_and_does_not_duplicate(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """6. Reusing today's intake does not change its metadata timestamp or duplicate files."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    source_file = init_dir / "Podcast Episode.mp4"
    source_file.write_bytes(b"podcast episode bytes 5555")

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    res1 = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )
    initial_timestamp = res1.metadata.ingested_at
    initial_mtime = res1.staged_path.stat().st_mtime

    res2 = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )

    # Metadata timestamp preserved unchanged
    assert res2.metadata.ingested_at == initial_timestamp
    # File mtime unchanged (not re-copied)
    assert res2.staged_path.stat().st_mtime == initial_mtime

    # Verify no duplicate video files inside the uuid directory
    parent_files = list(res2.staged_path.parent.glob("*.mp4"))
    assert len(parent_files) == 1


def test_7_both_date_folders_retain_same_canonical_source_uuid(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """7. Both date folders retain the same canonical source UUID."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    source_file = init_dir / "Viral Short.mp4"
    source_file.write_bytes(b"viral short content 7777")
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    res_oct29 = materialize_intake_video(source_file, input_root=input_dir, target_date=datetime.date(2026, 10, 29))
    res_oct31 = materialize_intake_video(source_file, input_root=input_dir, target_date=datetime.date(2026, 10, 31))

    assert res_oct29.metadata.video_id == res_oct31.metadata.video_id
    assert res_oct29.metadata.source_video_id == res_oct31.metadata.source_video_id
    
    # Assert canonical UUID validity
    assert uuid.UUID(res_oct29.metadata.source_video_id)
    assert not res_oct29.metadata.source_video_id.startswith("vid_")
    assert res_oct29.staged_path.parent.name == res_oct31.staged_path.parent.name


def test_8_corrupted_or_incomplete_today_intake_is_detected_and_repaired(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """8. An incomplete or invalid today's intake is detected and safely repaired."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    source_file = init_dir / "Corrupt Test.mp4"
    source_file.write_bytes(b"valid source video bytes 8888")

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Prepopulate a corrupt today's intake (0-byte video and broken metadata)
    hash_val = compute_file_sha256(source_file)
    source_uuid = generate_stable_video_id(hash_val)
    today_dir = input_dir / "2026-10-31" / source_uuid
    today_dir.mkdir(parents=True)
    corrupt_video = today_dir / "corrupt_test.mp4"
    corrupt_video.write_bytes(b"")  # 0 bytes!
    (today_dir / "metadata.json").write_text("{broken_json", encoding="utf-8")

    res = materialize_intake_video(
        source_file_path=source_file,
        input_root=input_dir,
        target_date=datetime.date(2026, 10, 31),
    )

    # Must be repaired cleanly
    assert res.is_staged is True
    assert res.staged_path.exists()
    assert res.staged_path.stat().st_size == len(b"valid source video bytes 8888")
    assert (today_dir / "metadata.json").exists()
    repaired_meta = IngestionMetadata.model_validate_json((today_dir / "metadata.json").read_text(encoding="utf-8"))
    assert repaired_meta.source_video_id == source_uuid
    assert repaired_meta.file_size_bytes == len(b"valid source video bytes 8888")


def test_9_missing_or_invalid_source_files_produce_clear_errors(tmp_path: Path):
    """9. Missing or invalid source files produce clear errors."""
    init_dir = tmp_path / "init_input"
    init_dir.mkdir()

    # Missing file
    with pytest.raises(FileNotFoundError) as exc_missing:
        resolve_source_videos(init_input_dir=init_dir, mode="single", single="non_existent.mp4")
    assert "not found in source library" in str(exc_missing.value)

    # Invalid file type
    invalid_file = init_dir / "document.pdf"
    invalid_file.write_bytes(b"pdf data")
    with pytest.raises(ValueError) as exc_invalid:
        resolve_source_videos(init_input_dir=init_dir, mode="single", single="document.pdf")
    assert "not a supported video file" in str(exc_invalid.value)

    # Invalid mode
    with pytest.raises(ValueError) as exc_mode:
        resolve_source_videos(init_input_dir=init_dir, mode="invalid_mode")
    assert "Invalid selection mode" in str(exc_mode.value)


def test_10_no_mode_selects_from_older_input_folder(tmp_path: Path):
    """10. No mode accidentally selects a video from an older input/ folder."""
    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    (init_dir / "authoritative.mp4").write_bytes(b"auth")

    older_input = tmp_path / "input" / "2026-10-29" / "uuid_old"
    older_input.mkdir(parents=True)
    (older_input / "older_copy.mp4").write_bytes(b"old")

    # Mode 'all'
    all_res = resolve_source_videos(init_input_dir=init_dir, mode="all")
    assert len(all_res) == 1
    assert all_res[0].name == "authoritative.mp4"
    assert "2026-10-29" not in str(all_res[0])

    # Attempting to select older copy fails because it does not exist in init_input/
    with pytest.raises(FileNotFoundError):
        resolve_source_videos(init_input_dir=init_dir, mode="single", single="older_copy.mp4")


def test_11_long_and_short_artifacts_retain_correct_source_uuid(
    tmp_path: Path, sample_transcript, monkeypatch
):
    """11. Long and short artifacts retain the correct source UUID."""
    source_uuid = str(uuid.uuid4())
    mgr = OutputManager(output_root=tmp_path / "outputs")
    run_dir = mgr.create_run_directory(source_uuid)

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"mock mp4 content")
        dur = kwargs.get("candidate_end_seconds", 30.0) - kwargs.get("candidate_start_seconds", 0.0)
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=1000,
            duration_seconds=dur,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)
    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    dummy_source = tmp_path / "dummy.mp4"
    dummy_source.write_bytes(b"dummy")

    # Render long clip
    long_uuid = str(uuid.uuid4())
    long_meta, long_item = render_long_clip_package(
        source_video_path=dummy_source,
        source_transcript=sample_transcript,
        clip_id=long_uuid,
        clip_index=1,
        source_start_seconds=0.0,
        source_end_seconds=30.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
    )
    assert long_meta.parent_id == source_uuid
    assert long_meta.source_video_id == source_uuid

    # Render short clip
    short_uuid = str(uuid.uuid4())
    short_meta, short_item = render_short_clip_package(
        parent_clean_master_path=run_dir / long_item.clean_master_path,
        parent_transcript=sample_transcript,
        parent_metadata=long_meta,
        clip_id=short_uuid,
        clip_index=1,
        parent_local_start_seconds=0.0,
        parent_local_end_seconds=15.0,
        run_dir=run_dir,
        output_manager=mgr,
    )
    assert short_meta.parent_id == long_uuid
    assert short_meta.source_video_id == source_uuid


@pytest.mark.asyncio
async def test_12_historical_run_discovery_and_media_access_still_work():
    """12. Existing historical run discovery and media access still work."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check listing available runs
        resp = await client.get("/api/v1/review/runs")
        assert resp.status_code == 200
        runs = resp.json()
        run_ids = [r["run_id"] for r in runs]
        
        # Verify historical run run_001_083927 is discoverable
        assert "run_001_083927" in run_ids
        
        # Verify recent validation run run_001_034641 is discoverable
        assert "run_001_034641" in run_ids

        # Verify media file streaming for historical run
        media_resp = await client.get("/api/v1/review/runs/run_001_083927/media/clip_01.mp4")
        assert media_resp.status_code == 200
        assert len(media_resp.content) > 0


@pytest.mark.asyncio
async def test_13_bounded_smoke_test_batch_runner_date_scoped_pipeline(
    tmp_path: Path, mock_video_probe, sample_transcript, monkeypatch
):
    """13. Bounded smoke test simulating the pipeline entry point:
    - Set up init_input/ with a video.
    - Prepopulate an older date intake input/2026-10-29/<source_uuid>/...
    - Run process_batch_items on date 2026-10-31 using mode 'single'.
    - Verify:
      1. Materialization created input/2026-10-31/<source_uuid>/video.mp4 and metadata.json.
      2. Historical input/2026-10-29/<source_uuid>/ was NOT reused and was preserved untouched.
      3. Both date folders have the same canonical UUID.
      4. Output was written to outputs/2026-10-31/<source_uuid>/<run_id>/.
      5. Manifest references match on-disk files.
    """
    init_dir = tmp_path / "init_input"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "outputs"
    init_dir.mkdir()
    input_dir.mkdir()
    output_dir.mkdir()

    # Source video in init_input/
    source_file = init_dir / "Jimmy Fallon Anne Hathaway.mp4"
    source_content = b"Simulated Anne Hathaway source content for smoke test 12345"
    source_file.write_bytes(source_content)
    source_hash = compute_file_sha256(source_file)
    source_uuid = generate_stable_video_id(source_hash)

    # Prepopulate historical intake in input/2026-10-29/<source_uuid>/
    old_date = "2026-10-29"
    old_intake_dir = input_dir / old_date / source_uuid
    old_intake_dir.mkdir(parents=True)
    old_video_file = old_intake_dir / "jimmy_fallon_anne_hathaway.mp4"
    old_video_file.write_bytes(source_content)
    old_meta = {
        "video_id": source_uuid,
        "source_video_id": source_uuid,
        "content_sha256": source_hash,
        "original_filename": "Jimmy Fallon Anne Hathaway.mp4",
        "file_size_bytes": len(source_content),
        "ingested_at": "2026-10-29T10:00:00Z",
    }
    old_meta_file = old_intake_dir / "metadata.json"
    old_meta_text = json.dumps(old_meta, indent=2)
    old_meta_file.write_text(old_meta_text, encoding="utf-8")
    old_meta_mtime = old_meta_file.stat().st_mtime_ns
    old_video_mtime = old_video_file.stat().st_mtime_ns

    # Select via resolve_source_videos in mode 'single'
    selected = resolve_source_videos(
        init_input_dir=init_dir,
        mode="single",
        single="Jimmy Fallon Anne Hathaway.mp4",
    )
    assert len(selected) == 1
    assert selected[0] == source_file.resolve()

    # Mock media probe
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)
    monkeypatch.setattr("app.services.pipeline.orchestrator.probe_media_file", lambda p: mock_video_probe)

    # Mock local transcription
    class MockLocalPipelineRes:
        artifact = sample_transcript

    monkeypatch.setattr(
        "app.services.pipeline.orchestrator.run_local_pipeline",
        lambda **kwargs: MockLocalPipelineRes(),
    )

    # Mock long clip discovery & rendering
    async def mock_discover_and_render_long(**kwargs):
        run_dir = kwargs["run_dir"]
        long_uuid = str(uuid.uuid4())
        long_dir = run_dir / "long_clips" / long_uuid
        long_dir.mkdir(parents=True, exist_ok=True)
        master_file = long_dir / f"{long_uuid}.mp4"
        master_file.write_bytes(b"long clip master")

        long_meta = ClipMetadata(
            schema_version="v1.0",
            clip_id=long_uuid,
            clip_type="long",
            source_video_id=kwargs["source_video_id"],
            parent_id=kwargs["source_video_id"],
            parent_type="source_video",
            timeline=ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=30.0,
                local_start_seconds=0.0,
                local_end_seconds=30.0,
                duration_seconds=30.0,
            ),
            status="clean_master_ready",
        )
        (long_dir / "metadata.json").write_text(long_meta.model_dump_json(indent=2), encoding="utf-8")

        return [
            ManifestLongClipItem(
                clip_id=long_uuid,
                folder=f"long_clips/{long_uuid}",
                source_start_seconds=0.0,
                source_end_seconds=30.0,
                duration_seconds=30.0,
                status="clean_master_ready",
                clean_master_path=f"long_clips/{long_uuid}/{long_uuid}.mp4",
            )
        ]

    monkeypatch.setattr(
        "app.services.pipeline.orchestrator.discover_and_render_long_clips",
        mock_discover_and_render_long,
    )

    # Mock short clip pipeline
    async def mock_run_short_pipeline(**kwargs):
        run_dir = kwargs["output_run_dir"]
        long_pkg_dir = kwargs["long_clip_dir"]
        parent_meta = json.loads((long_pkg_dir / "metadata.json").read_text(encoding="utf-8"))

        short_uuid = str(uuid.uuid4())
        short_dir = run_dir / "short_clips" / short_uuid
        short_dir.mkdir(parents=True, exist_ok=True)
        master_file = short_dir / f"{short_uuid}.mp4"
        master_file.write_bytes(b"short clip master")

        short_meta = ClipMetadata(
            schema_version="v1.0",
            clip_id=short_uuid,
            clip_type="short",
            source_video_id=parent_meta["source_video_id"],
            parent_id=parent_meta["clip_id"],
            parent_type="long_clip",
            timeline=ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=15.0,
                local_start_seconds=0.0,
                local_end_seconds=15.0,
                duration_seconds=15.0,
            ),
            status="clean_master_ready",
        )
        (short_dir / "metadata.json").write_text(short_meta.model_dump_json(indent=2), encoding="utf-8")

        item = ManifestShortClipItem(
            clip_id=short_uuid,
            parent_clip_id=parent_meta["clip_id"],
            folder=f"short_clips/{short_uuid}",
            source_start_seconds=0.0,
            source_end_seconds=15.0,
            parent_local_start_seconds=0.0,
            parent_local_end_seconds=15.0,
            duration_seconds=15.0,
            status="clean_master_ready",
            clean_master_path=f"short_clips/{short_uuid}/{short_uuid}.mp4",
        )
        return ShortPipelineResult(
            long_master_package=None,
            candidate_artifact=None,
            rendered_shorts=[short_meta],
            manifest_items=[item],
            candidates_count=1,
            rendered_count=1,
        )

    monkeypatch.setattr(
        "app.services.pipeline.orchestrator.run_short_clip_pipeline",
        mock_run_short_pipeline,
    )

    # Pin OutputManager timezone to 2026-10-31
    fixed_ist = datetime.datetime(
        2026, 10, 31, 14, 0, 0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    )
    monkeypatch.setattr(OutputManager, "get_ist_now", staticmethod(lambda: fixed_ist))

    # Initialize OutputManager with tmp outputs directory
    mgr = OutputManager(output_root=output_dir)

    # Execute batch runner for date 2026-10-31
    target_date = "2026-10-31"
    summary, exit_code = await process_batch_items(
        video_files=selected,
        input_root=input_dir,
        output_manager=mgr,
        target_date=target_date,
    )

    # Verification:
    assert exit_code == 0
    assert summary.successful_videos == 1
    assert summary.failed_videos == 0

    # 1. Materialization created input/2026-10-31/<source_uuid>/video.mp4 and metadata.json
    today_intake_dir = input_dir / target_date / source_uuid
    assert today_intake_dir.exists()
    today_video = today_intake_dir / "jimmy_fallon_anne_hathaway.mp4"
    assert today_video.exists()
    assert today_video.stat().st_size == len(source_content)
    today_meta_file = today_intake_dir / "metadata.json"
    assert today_meta_file.exists()
    today_meta = json.loads(today_meta_file.read_text(encoding="utf-8"))
    assert today_meta["video_id"] == source_uuid
    assert today_meta["source_video_id"] == source_uuid

    # 2. Historical input/2026-10-29/<source_uuid>/ was NOT reused and was preserved untouched
    assert old_intake_dir.exists()
    assert old_meta_file.read_text(encoding="utf-8") == old_meta_text
    assert old_meta_file.stat().st_mtime_ns == old_meta_mtime
    assert old_video_file.stat().st_mtime_ns == old_video_mtime

    # 3. Both date folders have the same canonical UUID
    assert today_meta["video_id"] == old_meta["video_id"] == source_uuid

    # 4. Output was written to outputs/2026-10-31/<source_uuid>/<run_id>/
    item_res = summary.items[0]
    run_dir = Path(item_res.run_dir)
    assert run_dir.parent == output_dir / target_date / source_uuid
    assert run_dir.name.startswith("run_001")

    # 5. Manifest references match on-disk files
    manifest_path = Path(item_res.manifest_path)
    assert manifest_path.exists()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "completed"
    assert manifest_data["source_video"]["video_id"] == source_uuid
    assert Path(manifest_data["source_video"]["source_path"]).resolve() == today_video.resolve()
    assert Path(item_res.staged_path).resolve() == today_video.resolve()

    long_ref = manifest_data["long_clips"][0]
    assert (run_dir / long_ref["clean_master_path"]).exists()
    assert (run_dir / long_ref["folder"] / "metadata.json").exists()

    short_ref = manifest_data["short_clips"][0]
    assert (run_dir / short_ref["clean_master_path"]).exists()
    assert (run_dir / short_ref["folder"] / "metadata.json").exists()
    assert short_ref["parent_clip_id"] == long_ref["clip_id"]
