"""Unit tests for OutputManager, directory hierarchy, and atomic operations."""

import datetime
from pathlib import Path
import pytest

from app.ai_clipper.services.storage.output_manager import OutputManager, IST


def test_get_run_directory_layout_and_collision(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    fixed_time = datetime.datetime(2026, 10, 24, 21, 30, 0, tzinfo=IST)

    # First run on empty folder: run_001_213000
    run_1 = mgr.get_run_directory("anne_hathaway", run_time=fixed_time)
    assert run_1.as_posix().endswith("2026-10-24/anne_hathaway/run_001_213000")

    # Simulate run_1 existing on disk
    run_1.mkdir(parents=True)

    # Second run: increments to run_002_213000
    run_2 = mgr.get_run_directory("anne_hathaway", run_time=fixed_time)
    assert run_2.as_posix().endswith("2026-10-24/anne_hathaway/run_002_213000")

    # Simulate run_2 existing
    run_2.mkdir(parents=True)

    # Third run: increments to run_003_213000
    run_3 = mgr.get_run_directory("anne_hathaway", run_time=fixed_time)
    assert run_3.as_posix().endswith("2026-10-24/anne_hathaway/run_003_213000")


def test_run_directory_sequence_with_historical_formats(tmp_path: Path):
    """Test that historical directories (HH_MM_SS__run_NNN) are recognized and counted."""
    mgr = OutputManager(output_root=tmp_path)
    fixed_time = datetime.datetime(2026, 10, 25, 3, 25, 0, tzinfo=IST)
    video_dir = tmp_path / "2026-10-25" / "anne_hathaway"
    video_dir.mkdir(parents=True)

    # Exactly matching scenario from prompt: 02_52_44__run_001 and 03_22_29__run_001
    (video_dir / "02_52_44__run_001").mkdir()
    (video_dir / "03_22_29__run_001").mkdir()

    # Next run must be run_003_HHMMSS (run_count = 2, max_seq = 1 -> next is 3)
    next_run = mgr.get_run_directory("anne_hathaway", run_time=fixed_time)
    assert next_run.name == "run_003_032500"

    # Now create run_003 on disk using create_run_directory
    created_dir = mgr.create_run_directory("anne_hathaway", run_time=fixed_time)
    assert created_dir.name == "run_003_032500"
    assert created_dir.exists()

    # Following run should be run_004
    following_time = datetime.datetime(2026, 10, 25, 4, 0, 0, tzinfo=IST)
    run_4 = mgr.get_run_directory("anne_hathaway", run_time=following_time)
    assert run_4.name == "run_004_040000"


def test_run_directory_sequence_with_failed_runs_and_custom_dirs(tmp_path: Path):
    """Failed or partial run directories (containing manifest/transcript) count toward sequence."""
    mgr = OutputManager(output_root=tmp_path)
    fixed_time = datetime.datetime(2026, 10, 25, 12, 0, 0, tzinfo=IST)
    video_dir = tmp_path / "2026-10-25" / "custom_test"
    video_dir.mkdir(parents=True)

    # Create a non-standard named failed run folder with a manifest
    failed_dir = video_dir / "failed_attempt_alpha"
    failed_dir.mkdir()
    (failed_dir / "manifest.json").write_text('{"status": "failed"}')

    # Next run should see 1 existing attempt and start at run_002
    run = mgr.get_run_directory("custom_test", run_time=fixed_time)
    assert run.name == "run_002_120000"


def test_create_run_directory_atomic_collision_handling(tmp_path: Path):
    """Simulate directory collision during create_run_directory to verify auto-increment."""
    mgr = OutputManager(output_root=tmp_path)
    fixed_time = datetime.datetime(2026, 10, 25, 14, 0, 0, tzinfo=IST)

    # Pre-create candidate run_001_140000 manually
    video_dir = tmp_path / "2026-10-25" / "test_video"
    video_dir.mkdir(parents=True)
    (video_dir / "run_001_140000").mkdir()

    # create_run_directory should safely increment to run_002_140000
    created = mgr.create_run_directory("test_video", run_time=fixed_time)
    assert created.name == "run_002_140000"
    assert created.is_dir()


def test_create_run_directory_and_clip_subdirs(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    run_dir = mgr.create_run_directory("podcast_ep")
    assert run_dir.exists()

    long_clip_1 = mgr.get_long_clip_dir(run_dir, 1)
    short_clip_2 = mgr.get_short_clip_dir(run_dir, 2)

    assert long_clip_1.as_posix().endswith("long_clips/clip_01")
    assert short_clip_2.as_posix().endswith("short_clips/clip_02")


def test_write_text_and_json_atomic(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    text_target = tmp_path / "subfolder" / "message.txt"

    mgr.write_text_atomic(text_target, "Hello Atomic World")
    assert text_target.exists()
    assert text_target.read_text(encoding="utf-8") == "Hello Atomic World"

    # No leftover temporary files
    assert len(list(text_target.parent.glob(".*.tmp*"))) == 0

    json_target = tmp_path / "subfolder" / "data.json"
    data = {"pipeline": "full", "score": 95}
    mgr.write_json_atomic(json_target, data)
    assert json_target.exists()
    loaded = mgr.read_json(json_target)
    assert loaded == data


def test_stage_media_path_success(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    final_video = tmp_path / "render" / "clip_01.mp4"

    with mgr.stage_media_path(final_video) as staging_file:
        assert staging_file.name == "clip_01.rendering.mp4"
        assert not final_video.exists()
        # Simulate rendering output to staging file
        staging_file.write_text("rendered video bytes")

    # Upon successful context exit, staging file is promoted to final_video
    assert final_video.exists()
    assert final_video.read_text() == "rendered video bytes"
    assert not staging_file.exists()


def test_stage_media_path_failure_cleanup(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    final_video = tmp_path / "render" / "clip_02.mp4"

    with pytest.raises(RuntimeError, match="FFmpeg simulation crashed"):
        with mgr.stage_media_path(final_video) as staging_file:
            staging_file.write_text("partial corrupt render")
            raise RuntimeError("FFmpeg simulation crashed")

    # Staging file is cleaned up, and final_video is not created
    assert not final_video.exists()
    assert not staging_file.exists()
