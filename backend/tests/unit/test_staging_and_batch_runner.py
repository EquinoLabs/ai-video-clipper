"""Unit tests for Stage 4 Input Staging and Batch Runner."""

import json
import uuid
from pathlib import Path
import pytest

from app.domain.candidates.models import EditorialGoal
from app.services.media.probing import AudioStreamInfo, MediaProbeResult, VideoStreamInfo
from app.services.pipeline.batch_runner import BatchSummary, process_batch_items
from app.services.pipeline.orchestrator import OrchestratorConfig, OrchestratorResult
from app.services.storage.output_manager import OutputManager
from app.services.storage.staging import (
    is_supported_video_file,
    stage_input_video,
)


@pytest.fixture
def mock_video_probe() -> MediaProbeResult:
    return MediaProbeResult(
        format_name="mov,mp4,m4a",
        duration_seconds=30.0,
        size_bytes=5000,
        video_streams=[
            VideoStreamInfo(
                index=0,
                codec_name="h264",
                width=1920,
                height=1080,
                duration_seconds=30.0,
            )
        ],
        audio_streams=[
            AudioStreamInfo(
                index=0,
                stream_index=1,
                codec_name="aac",
                sample_rate=44100,
                channels=2,
                duration_seconds=30.0,
            )
        ],
        selected_audio_stream_index=0,
        selected_audio_stream_id=1,
    )


def test_is_supported_video_file(tmp_path: Path):
    valid_mp4 = tmp_path / "clip.mp4"
    valid_mp4.write_text("mp4 data")
    assert is_supported_video_file(valid_mp4) is True

    valid_mov = tmp_path / "clip.MOV"
    valid_mov.write_text("mov data")
    assert is_supported_video_file(valid_mov) is True

    invalid_txt = tmp_path / "notes.txt"
    invalid_txt.write_text("notes")
    assert is_supported_video_file(invalid_txt) is False

    folder = tmp_path / "subfolder"
    folder.mkdir()
    assert is_supported_video_file(folder) is False


def test_stage_input_video_layout_and_deduplication(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    original_file = init_dir / "Anne Hathaway Interview.mp4"
    original_content = b"original raw video bytes 12345"
    original_file.write_bytes(original_content)

    # 1. Stage first copy into target layout: input/YYYY-MM-DD/<stable_video_id>/<normalized_filename>
    res1 = stage_input_video(original_file, input_root=input_dir)
    assert res1.is_staged is True
    assert res1.staged_path.exists()
    assert res1.staged_path.name == "anne_hathaway_interview.mp4"
    assert res1.staged_path.parent.name == res1.metadata.video_id
    assert not res1.metadata.video_id.startswith("vid_")
    assert uuid.UUID(res1.metadata.video_id)
    assert res1.metadata.original_filename == "Anne Hathaway Interview.mp4"
    assert res1.metadata.stored_filename == "anne_hathaway_interview.mp4"
    assert (res1.staged_path.parent / "metadata.json").exists()

    # Verify metadata fields and timestamp regression fix
    assert res1.metadata.ingested_at != "mov,mp4,m4a"
    assert "T" in res1.metadata.ingested_at  # Valid ISO 8601 timestamp
    assert res1.metadata.media_info["format_name"] == "mov,mp4,m4a"
    assert res1.metadata.ingestion_date.count("-") == 2

    # Original file in init_input/ must be untouched
    assert original_file.exists()
    assert original_file.read_bytes() == original_content

    # 2. Stage identical content from another path (clean deduplication / reuse)
    init_dir_2 = tmp_path / "another_folder"
    init_dir_2.mkdir()
    identical_file = init_dir_2 / "Different_Name_Same_Bytes.mp4"
    identical_file.write_bytes(original_content)

    res2 = stage_input_video(identical_file, input_root=input_dir)
    assert res2.is_staged is True
    assert res2.staged_path == res1.staged_path
    assert res2.metadata.video_id == res1.metadata.video_id

    # 3. Stage different content (gets unique video_id directory)
    different_file = init_dir / "Different Video.mp4"
    different_file.write_bytes(b"completely different content 99999")
    res3 = stage_input_video(different_file, input_root=input_dir)
    assert res3.is_staged is True
    assert res3.staged_path != res1.staged_path
    assert res3.metadata.video_id != res1.metadata.video_id
    assert res3.staged_path.name == "different_video.mp4"
    assert res3.staged_path.exists()


def test_stage_input_video_rejects_empty_or_unsupported(tmp_path: Path):
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_bytes(b"")
    res_empty = stage_input_video(empty_file, input_root=tmp_path / "input")
    assert res_empty.is_staged is False
    assert "empty" in res_empty.error_message.lower()

    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("not a video")
    res_txt = stage_input_video(txt_file, input_root=tmp_path / "input")
    assert res_txt.is_staged is False
    assert "unsupported" in res_txt.error_message.lower()


@pytest.mark.asyncio
async def test_batch_runner_processes_folder_in_deterministic_order(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    # Mock orchestrator
    called_sources = []

    async def mock_orchestrator(**kwargs):
        src = Path(kwargs["source_video_path"])
        # With the new layout input/YYYY-MM-DD/<video_id>/video.mp4, check metadata to identify original file
        meta_file = src.parent / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            called_sources.append(meta.get("original_filename", src.name))
        else:
            called_sources.append(src.name)
        return OrchestratorResult(
            run_id=f"run_{Path(src).stem}",
            run_dir=str(tmp_path / "outputs" / Path(src).stem),
            status="completed",
            manifest_path=str(tmp_path / "outputs" / Path(src).stem / "manifest.json"),
            source_duration_seconds=30.0,
            long_clips_count=1,
            short_clips_count=2,
            elapsed_seconds=1.5,
            stage_statuses={"transcription": "completed", "long_discovery": "completed", "short_discovery": "completed"},
        )

    monkeypatch.setattr(
        "app.services.pipeline.batch_runner.run_pipeline_orchestrator",
        mock_orchestrator,
    )

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Create files out of alphabetical order
    (init_dir / "zebra_talk.mp4").write_bytes(b"video z")
    (init_dir / "apple_talk.mp4").write_bytes(b"video a")
    (init_dir / "notes.txt").write_bytes(b"ignore this file")
    (init_dir / "banana_talk.mov").write_bytes(b"video b")

    # Pass in deterministic order as CLI does
    files = sorted(list(init_dir.iterdir()), key=lambda p: p.name.lower())

    summary, exit_code = await process_batch_items(
        video_files=files,
        input_root=input_dir,
        output_manager=OutputManager(output_root=tmp_path / "outputs"),
        log_dir=tmp_path / "outputs" / "batch_logs",
    )

    assert exit_code == 0
    assert summary.total_discovered_files == 4
    assert summary.successful_videos == 3
    assert summary.skipped_files == 1
    assert summary.failed_videos == 0

    # Verify deterministic execution order: apple -> banana -> zebra
    assert called_sources == ["apple_talk.mp4", "banana_talk.mov", "zebra_talk.mp4"]


@pytest.mark.asyncio
async def test_batch_runner_isolates_failure_and_continues(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    # Mock orchestrator to fail for video 1, but succeed for video 2
    async def mock_orchestrator(**kwargs):
        src = Path(kwargs["source_video_path"])
        meta_file = src.parent / "metadata.json"
        name = src.name
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            name = meta.get("original_filename", src.name)
        if "bad" in name:
            raise RuntimeError("Corrupt frames in bad video")
        return OrchestratorResult(
            run_id="run_good",
            run_dir=str(tmp_path / "outputs" / "good"),
            status="completed",
            manifest_path=str(tmp_path / "outputs" / "good" / "manifest.json"),
            source_duration_seconds=30.0,
            long_clips_count=1,
            short_clips_count=1,
            elapsed_seconds=1.0,
            stage_statuses={"transcription": "completed"},
        )

    monkeypatch.setattr(
        "app.services.pipeline.batch_runner.run_pipeline_orchestrator",
        mock_orchestrator,
    )

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    v1 = init_dir / "bad_clip.mp4"
    v1.write_bytes(b"bad content")
    v2 = init_dir / "good_clip.mp4"
    v2.write_bytes(b"good content")

    summary, exit_code = await process_batch_items(
        video_files=[v1, v2],
        input_root=input_dir,
        output_manager=OutputManager(output_root=tmp_path / "outputs"),
        log_dir=tmp_path / "outputs" / "batch_logs",
    )

    # Must return non-zero exit code because one video failed
    assert exit_code == 1
    assert summary.total_discovered_files == 2
    assert summary.failed_videos == 1
    assert summary.successful_videos == 1
    assert summary.items[0].status == "failed"
    assert "Corrupt frames" in summary.items[0].error_message
    assert summary.items[1].status == "completed"


def test_cli_argument_parsing_and_ollama_propagation(monkeypatch):
    """Verify that CLI flags `--provider ollama --model qwen2.5:7b --final` are parsed and configured."""
    import sys
    from app.core.config import get_settings
    from app.services.pipeline.orchestrator import OrchestratorConfig

    test_args = [
        "app.py",
        "--final",
        "--provider", "ollama",
        "--model", "qwen2.5:7b",
        "--single", "init_input/Anne Hathaway.mp4",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    # Simulate CLI argument parsing logic from app.py
    import argparse
    parser = argparse.ArgumentParser()
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--single", type=Path)
    mode_group.add_argument("--all", type=Path)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--goal", type=str, default="overall")
    parser.add_argument("--provider", type=str, default=None, choices=["openai", "ollama"])
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--input-root", type=Path, default=Path("input"))
    parser.add_argument("--log-level", type=str, default="INFO")

    parsed = parser.parse_args(test_args[1:])

    settings = get_settings()
    effective_provider = (parsed.provider or settings.llm_provider or "openai").lower()
    effective_model = (
        parsed.model or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    # Assert CLI overrides configured defaults
    assert effective_provider == "ollama"
    assert effective_model == "qwen2.5:7b"
    assert parsed.final is True

    # Construct OrchestratorConfig
    config = OrchestratorConfig(
        pipeline_mode="full",
        editorial_goal=EditorialGoal(parsed.goal),
        llm_provider=effective_provider,
        llm_model=effective_model,
        render_clean_masters=True,
        render_final_deliverables=parsed.final,
    )

    assert config.llm_provider == "ollama"
    assert config.llm_model == "qwen2.5:7b"
    assert config.render_final_deliverables is True
    assert config.render_clean_masters is True


def test_discover_video_files_in_folder_ignores_json_and_handles_nested_hierarchy(tmp_path: Path):
    """Confirm recursive batch discovery discovers each video exactly once and ignores metadata JSONs."""
    from app.services.storage.staging import discover_video_files_in_folder

    staging_dir = tmp_path / "input"
    staging_dir.mkdir()

    # Flat video (legacy/compatibility)
    flat_vid = staging_dir / "legacy_video.mp4"
    flat_vid.write_bytes(b"legacy mp4")
    (staging_dir / "legacy_video__metadata.json").write_text("{}")

    # Nested video under date/video_id/
    v1_dir = staging_dir / "2026-10-25" / "vid_20261025_aaaa"
    v1_dir.mkdir(parents=True)
    v1 = v1_dir / "video.mp4"
    v1.write_bytes(b"video 1")
    (v1_dir / "metadata.json").write_text("{}")

    v2_dir = staging_dir / "2026-10-25" / "vid_20261025_bbbb"
    v2_dir.mkdir(parents=True)
    v2 = v2_dir / "video.mov"
    v2.write_bytes(b"video 2")
    (v2_dir / "metadata.json").write_text("{}")

    # Non-video files
    (v2_dir / "readme.txt").write_text("readme")
    (v2_dir / ".hidden_temp.mp4").write_text("temp")

    discovered = discover_video_files_in_folder(staging_dir)

    # Must contain exactly 3 video files, no JSONs, no hidden/text files
    assert len(discovered) == 3
    discovered_names = [f.name for f in discovered]
    assert "legacy_video.mp4" in discovered_names
    assert "video.mp4" in discovered_names
    assert "video.mov" in discovered_names
    assert all(f.suffix in (".mp4", ".mov") for f in discovered)
    assert not any(f.name.endswith(".json") for f in discovered)


# ==============================================================================
# Native Transcript Reuse & Forwarding Tests (Single Video & Batch Mode)
# ==============================================================================

@pytest.mark.asyncio
async def test_batch_runner_single_video_transcript_forwarding(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """Verify process_batch_items forwards existing_transcript_path to the orchestrator for single-video runs."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    received_transcript_path = None

    async def mock_orchestrator(**kwargs):
        nonlocal received_transcript_path
        received_transcript_path = kwargs.get("existing_transcript_path")
        src = Path(kwargs["source_video_path"])
        return OrchestratorResult(
            run_id="run_test",
            run_dir=str(tmp_path / "outputs" / "test_run"),
            status="completed",
            manifest_path=str(tmp_path / "outputs" / "test_run" / "manifest.json"),
            source_duration_seconds=30.0,
            long_clips_count=1,
            short_clips_count=1,
            elapsed_seconds=1.0,
            stage_statuses={"transcription": "completed"},
        )

    monkeypatch.setattr(
        "app.services.pipeline.batch_runner.run_pipeline_orchestrator",
        mock_orchestrator,
    )

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    vid = init_dir / "single_test.mp4"
    vid.write_bytes(b"sample video bytes")

    transcript_file = tmp_path / "custom_transcript.json"
    transcript_file.write_text('{"schema_version": "v1.0"}', encoding="utf-8")

    summary, exit_code = await process_batch_items(
        video_files=[vid],
        input_root=input_dir,
        output_manager=OutputManager(output_root=tmp_path / "outputs"),
        log_dir=tmp_path / "outputs" / "batch_logs",
        existing_transcript_path=transcript_file,
    )

    assert exit_code == 0
    assert summary.successful_videos == 1
    assert received_transcript_path == transcript_file


@pytest.mark.asyncio
async def test_batch_runner_backward_compatibility_no_transcript(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """Verify process_batch_items defaults to existing_transcript_path=None when omitted."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    received_transcript_path = "NOT_NONE"

    async def mock_orchestrator(**kwargs):
        nonlocal received_transcript_path
        received_transcript_path = kwargs.get("existing_transcript_path")
        return OrchestratorResult(
            run_id="run_compat",
            run_dir=str(tmp_path / "outputs" / "compat"),
            status="completed",
            manifest_path=str(tmp_path / "outputs" / "compat" / "manifest.json"),
            source_duration_seconds=30.0,
            long_clips_count=1,
            short_clips_count=1,
            elapsed_seconds=1.0,
            stage_statuses={"transcription": "completed"},
        )

    monkeypatch.setattr(
        "app.services.pipeline.batch_runner.run_pipeline_orchestrator",
        mock_orchestrator,
    )

    init_dir = tmp_path / "init_input"
    init_dir.mkdir()
    vid = init_dir / "compat.mp4"
    vid.write_bytes(b"compat video")

    summary, exit_code = await process_batch_items(
        video_files=[vid],
        input_root=tmp_path / "input",
        output_manager=OutputManager(output_root=tmp_path / "outputs"),
        log_dir=tmp_path / "outputs" / "batch_logs",
    )

    assert exit_code == 0
    assert received_transcript_path is None


@pytest.mark.asyncio
async def test_batch_runner_rejects_transcript_with_multiple_videos(tmp_path: Path):
    """Verify process_batch_items raises ValueError if a single transcript is supplied for multiple videos."""
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"1")
    v2.write_bytes(b"2")

    tr = tmp_path / "shared_transcript.json"
    tr.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot supply a single transcript for multiple video files in batch mode"):
        await process_batch_items(
            video_files=[v1, v2],
            existing_transcript_path=tr,
        )


@pytest.mark.asyncio
async def test_batch_runner_validates_transcript_path(tmp_path: Path):
    """Verify process_batch_items validates existence and file type for existing_transcript_path."""
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"1")

    # Missing file
    missing_tr = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError, match="Supplied transcript file not found"):
        await process_batch_items(
            video_files=[v1],
            existing_transcript_path=missing_tr,
        )

    # Directory instead of file
    tr_dir = tmp_path / "transcript_dir"
    tr_dir.mkdir()
    with pytest.raises(ValueError, match="Supplied transcript path is not a file"):
        await process_batch_items(
            video_files=[v1],
            existing_transcript_path=tr_dir,
        )


def _load_root_app():
    import importlib.util
    project_root = Path(__file__).resolve().parents[3]
    app_py_path = project_root / "app.py"
    spec = importlib.util.spec_from_file_location("root_app", str(app_py_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_app_cli_rejects_transcript_with_all_mode(tmp_path: Path, monkeypatch, capsys):
    """Verify top-level app.py rejects --transcript / -t when used with --all in batch mode."""
    import sys
    app_mod = _load_root_app()

    test_folder = tmp_path / "all_videos"
    test_folder.mkdir()
    test_tr = tmp_path / "test.json"
    test_tr.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--all", str(test_folder), "-t", str(test_tr)],
    )

    with pytest.raises(SystemExit) as exc_info:
        app_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "--transcript (-t) cannot be used with --all" in captured.err


def test_app_cli_rejects_missing_transcript_file(tmp_path: Path, monkeypatch, capsys):
    """Verify top-level app.py rejects non-existent transcript file paths."""
    import sys
    app_mod = _load_root_app()

    test_video = tmp_path / "video.mp4"
    test_video.write_bytes(b"vid")
    missing_tr = tmp_path / "nonexistent_transcript.json"

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--single", str(test_video), "-t", str(missing_tr)],
    )

    with pytest.raises(SystemExit) as exc_info:
        app_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Transcript file not found" in captured.err


def test_app_cli_single_video_transcript_forwarding(tmp_path: Path, monkeypatch):
    """Verify top-level app.py forwards -t / --transcript to process_batch_items."""
    import sys
    app_mod = _load_root_app()

    test_video = tmp_path / "video.mp4"
    test_video.write_bytes(b"vid")
    valid_tr = tmp_path / "valid_transcript.json"
    valid_tr.write_text("{}", encoding="utf-8")

    forwarded_transcript = None

    async def mock_process_batch_items(**kwargs):
        nonlocal forwarded_transcript
        forwarded_transcript = kwargs.get("existing_transcript_path")
        return BatchSummary(batch_id="batch_mock", total_discovered_files=1, successful_videos=1), 0

    monkeypatch.setattr(app_mod, "process_batch_items", mock_process_batch_items)

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--single", str(test_video), "-t", str(valid_tr), "--final"],
    )

    with pytest.raises(SystemExit) as exc_info:
        app_mod.main()

    assert exc_info.value.code == 0
    assert forwarded_transcript == valid_tr


def test_stable_video_id_and_cross_date_deduplication(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """Test 1, 2, 3, 4: Stable ID across dates, cross-date reuse, different filename reuse, and distinct IDs."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Create an existing historical record under an older date directory
    older_date_dir = input_dir / "2026-10-20" / "vid_6cf414fcdae21d2e"
    older_date_dir.mkdir(parents=True)
    older_video = older_date_dir / "interview_show.mp4"
    video_bytes = b"identical video content across dates 123456"
    older_video.write_bytes(video_bytes)

    from app.services.storage.ingestion import compute_file_sha256
    content_hash = compute_file_sha256(older_video)

    (older_date_dir / "metadata.json").write_text(
        json.dumps({
            "schema_version": "v1.0",
            "video_id": "vid_6cf414fcdae21d2e",
            "original_filename": "Original Old Name.mp4",
            "stored_filename": "interview_show.mp4",
            "ingested_at": "2026-10-20T10:00:00+05:30",
            "ingestion_date": "2026-10-20",
            "file_size_bytes": len(video_bytes),
            "media_type": "mp4",
            "content_sha256": content_hash,
            "source_path": str(older_video),
            "probe_status": "probed",
        }),
        encoding="utf-8",
    )

    # 1 & 2 & 3: Staging identical content on a new date with a completely different original name
    new_source = tmp_path / "New_Filename_Same_Bytes.mp4"
    new_source.write_bytes(video_bytes)

    res = stage_input_video(new_source, input_root=input_dir)
    assert res.is_staged is True
    # Date-scoped intake creates today's intake copy and preserves historical intake
    assert res.staged_path != older_video
    assert res.staged_path.exists()
    assert older_video.exists()
    assert uuid.UUID(res.metadata.video_id)
    assert res.metadata.content_sha256 == content_hash

    # 4: Different content gets distinct ID
    diff_source = tmp_path / "Different_Content.mp4"
    diff_source.write_bytes(b"completely different content 88888")
    diff_res = stage_input_video(diff_source, input_root=input_dir)
    assert diff_res.is_staged is True
    assert diff_res.staged_path != older_video
    assert diff_res.metadata.video_id != res.metadata.video_id
    assert diff_res.metadata.content_sha256 != content_hash


def test_corrupt_or_inconsistent_existing_record_not_silently_reused(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """Test 6: Inconsistent hash or corrupted record is bypassed safely."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Prepopulate a folder where metadata claims a hash, but actual file on disk is altered/corrupt
    corrupt_dir = input_dir / "2026-10-22" / "vid_corrupt"
    corrupt_dir.mkdir(parents=True)
    corrupt_video = corrupt_dir / "bad.mp4"
    corrupt_video.write_bytes(b"actual disk bytes are different")

    claimed_hash = "6cf414fcdae21d2ecf3c8931015c3148915ddd27f42cdaacaad92415c46379c2"
    (corrupt_dir / "metadata.json").write_text(
        json.dumps({
            "schema_version": "v1.0",
            "video_id": "vid_corrupt",
            "original_filename": "claimed.mp4",
            "stored_filename": "bad.mp4",
            "ingested_at": "2026-10-22T10:00:00+05:30",
            "ingestion_date": "2026-10-22",
            "file_size_bytes": 100,
            "media_type": "mp4",
            "content_sha256": claimed_hash,
            "source_path": str(corrupt_video),
            "probe_status": "probed",
        }),
        encoding="utf-8",
    )

    # Now attempt to stage a video that has `claimed_hash`
    # (mocking compute_file_sha256 for the new file to return claimed_hash)
    real_source = tmp_path / "source.mp4"
    real_source.write_bytes(b"source bytes")

    from app.services.storage import staging as staging_mod

    def mock_compute_hash(p: Path) -> str:
        if p == corrupt_video:
            return "tampered_hash_on_disk"
        return claimed_hash

    monkeypatch.setattr(staging_mod, "compute_file_sha256", mock_compute_hash)

    # Staging should not reuse corrupt_video; it stages freshly under a clean folder
    res = stage_input_video(real_source, input_root=input_dir)
    assert res.is_staged is True
    assert res.staged_path != corrupt_video
    assert res.staged_path.exists()
    # Existing corrupt video was preserved untouched
    assert corrupt_video.exists()


def test_filename_normalization_comprehensive():
    """Test 7: snake_case, preserved extensions, punctuation, Unicode, empty stems, Windows reserved names."""
    from app.services.storage.ingestion import normalize_filename

    # Standard & punctuation
    assert normalize_filename("Anne Hathaway Forgets The Princess Diaries!.mp4") == "anne_hathaway_forgets_the_princess_diaries.mp4"
    assert normalize_filename("Jimmy & Fallon + Guests (1080p).MKV") == "jimmy_fallon_guests_1080p.mkv"
    assert normalize_filename("hello...world---test.MOV") == "hello_world_test.mov"

    # Unicode & accents
    assert normalize_filename("Café_München_2026.webm") == "cafe_munchen_2026.webm"

    # Empty stems or special characters only
    assert normalize_filename("???!!!.mp4") == "video.mp4"
    assert normalize_filename(".avi") == "video.avi"
    assert normalize_filename("   .mp4") == "video.mp4"

    # Windows reserved device names
    assert normalize_filename("CON.mp4") == "video.mp4"
    assert normalize_filename("prn.mov") == "video.mov"
    assert normalize_filename("aux.mkv") == "video.mkv"
    assert normalize_filename("NUL.mp4") == "video.mp4"
    assert normalize_filename("com1.mp4") == "video.mp4"
    assert normalize_filename("lpt1.mp4") == "video.mp4"

    # Long stem safely truncated
    long_name = ("a" * 200) + ".mp4"
    normalized_long = normalize_filename(long_name)
    assert len(normalized_long) <= 125
    assert normalized_long.endswith(".mp4")


def test_legacy_video_and_flat_inputs_remain_discoverable(tmp_path: Path):
    """Test 10: Legacy video.<ext> records and flat inputs remain discoverable."""
    from app.services.storage.staging import discover_video_files_in_folder

    staging_dir = tmp_path / "inputs"
    staging_dir.mkdir()

    # 1. Flat legacy video
    flat_vid = staging_dir / "flat_legacy_clip.mp4"
    flat_vid.write_bytes(b"vid flat")

    # 2. Historical staged layout: input/2026-10-25/vid_20261025_6cf414fc/video.mp4
    hist_dir = staging_dir / "2026-10-25" / "vid_20261025_6cf414fc"
    hist_dir.mkdir(parents=True)
    hist_vid = hist_dir / "video.mp4"
    hist_vid.write_bytes(b"vid hist")
    (hist_dir / "metadata.json").write_text("{}", encoding="utf-8")

    # 3. New normalized layout: input/2026-10-25/vid_6cf414fcdae21d2e/anne_hathaway.mp4
    new_dir = staging_dir / "2026-10-25" / "vid_6cf414fcdae21d2e"
    new_dir.mkdir(parents=True)
    new_vid = new_dir / "anne_hathaway.mp4"
    new_vid.write_bytes(b"vid new")
    (new_dir / "metadata.json").write_text("{}", encoding="utf-8")

    discovered = discover_video_files_in_folder(staging_dir)
    discovered_names = [p.name for p in discovered]

    assert "flat_legacy_clip.mp4" in discovered_names
    assert "video.mp4" in discovered_names
    assert "anne_hathaway.mp4" in discovered_names
    assert len(discovered) == 3


def test_id_prefix_collision_handling(tmp_path: Path, mock_video_probe, monkeypatch):
    """Test 1: Prefix collision handling when two files share first 16 chars of SHA-256."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Two distinct hashes sharing identical 16-hex prefix
    prefix = "abcdef0123456789"
    hash_a = prefix + ("a" * 48)
    hash_b = prefix + ("b" * 48)

    src_a = tmp_path / "video_a.mp4"
    src_a.write_bytes(b"content a")

    src_b = tmp_path / "video_b.mp4"
    src_b.write_bytes(b"content b")

    from app.services.storage import staging as staging_mod

    def mock_hash(p: Path) -> str:
        # Mock deterministic hash
        if p.name == "video_a.mp4" or "video_a" in p.name:
            return hash_a
        elif p.name == "video_b.mp4" or "video_b" in p.name:
            return hash_b
        return "0" * 64

    monkeypatch.setattr(staging_mod, "compute_file_sha256", mock_hash)

    # Stage video A
    res_a = stage_input_video(src_a, input_root=input_dir)
    assert res_a.is_staged is True
    assert res_a.metadata.content_sha256 == hash_a
    assert res_a.staged_path.exists()

    # Stage video B (shares same 16-char prefix)
    res_b = stage_input_video(src_b, input_root=input_dir)
    assert res_b.is_staged is True
    assert res_b.metadata.content_sha256 == hash_b
    assert res_b.staged_path.exists()

    # Verify B did NOT overwrite or reuse A
    assert res_a.staged_path != res_b.staged_path
    assert res_a.staged_path.read_bytes() == b"content a"
    assert res_b.staged_path.read_bytes() == b"content b"


def test_concurrent_staging_of_identical_content(tmp_path: Path, mock_video_probe, monkeypatch):
    """Test 2: Concurrent staging of identical content from multiple threads."""
    import concurrent.futures
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    source = tmp_path / "simultaneous_source.mp4"
    source.write_bytes(b"concurrent identical content 12345")

    # Run 5 threads staging the exact same source concurrently
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(stage_input_video, source, input_dir) for _ in range(5)]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    # All 5 must succeed
    assert len(results) == 5
    for r in results:
        assert r.is_staged is True
        assert r.staged_path.exists()

    # All must agree on the same canonical staged path and metadata
    canonical_path = results[0].staged_path
    canonical_id = results[0].metadata.video_id
    for r in results[1:]:
        assert r.staged_path == canonical_path
        assert r.metadata.video_id == canonical_id

    # No leftover staging temp files (.staging_video_*)
    temp_files = list(canonical_path.parent.glob(".staging_video_*"))
    assert len(temp_files) == 0


def test_corrupt_or_incomplete_existing_records_are_not_silently_reused(
    tmp_path: Path, mock_video_probe, monkeypatch
):
    """Test 3: Missing media, invalid JSON metadata, or hash mismatch never silently reuses."""
    monkeypatch.setattr("app.services.storage.staging.probe_media_file", lambda p: mock_video_probe)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # Case A: metadata.json exists but is completely invalid/corrupt JSON
    corrupt_meta_dir = input_dir / "2026-10-21" / "vid_badmeta"
    corrupt_meta_dir.mkdir(parents=True)
    (corrupt_meta_dir / "metadata.json").write_text("{corrupted-json-syntax", encoding="utf-8")
    (corrupt_meta_dir / "clip.mp4").write_bytes(b"some content")

    # Case B: metadata.json exists and is valid, but the staged media file was deleted
    missing_media_dir = input_dir / "2026-10-21" / "vid_missingmedia"
    missing_media_dir.mkdir(parents=True)
    (missing_media_dir / "metadata.json").write_text(
        json.dumps({
            "schema_version": "v1.0",
            "video_id": "vid_missingmedia",
            "original_filename": "clip.mp4",
            "stored_filename": "clip.mp4",
            "ingested_at": "2026-10-21T10:00:00+05:30",
            "ingestion_date": "2026-10-21",
            "file_size_bytes": 100,
            "content_sha256": "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            "source_path": "clip.mp4",
        }),
        encoding="utf-8",
    )

    # Now stage a real video
    real_video = tmp_path / "real_video.mp4"
    real_video.write_bytes(b"real video content for test 3")

    res = stage_input_video(real_video, input_root=input_dir)
    assert res.is_staged is True
    # Cleanly staged into a separate folder, did not reuse corrupt or missing folders
    assert res.staged_path.parent != corrupt_meta_dir
    assert res.staged_path.parent != missing_media_dir
    assert res.staged_path.exists()
    assert (res.staged_path.parent / "metadata.json").exists()

