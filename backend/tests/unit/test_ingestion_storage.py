"""Unit tests for ingestion storage, filename normalization, and metadata persistence."""

import datetime
from pathlib import Path
import pytest

from app.domain.ingestion.models import IngestionMetadata
import uuid
from app.services.storage.ingestion import (
    compute_file_sha256,
    ingest_source_video,
    load_ingestion_metadata,
    normalize_filename,
    resolve_unique_input_path,
    save_ingestion_metadata,
)


def test_normalize_filename_standard_and_edge_cases():
    # Standard mixed-case and spaces
    assert normalize_filename("Anne Hathaway Tonight Show.mp4") == "anne_hathaway_tonight_show.mp4"
    assert normalize_filename("PODCAST--EPISODE__42!!.MOV") == "podcast_episode_42.mov"

    # Multi-dot filenames
    assert normalize_filename("my.video.final.v2.mp4") == "my_video_final_v2.mp4"

    # Accents and unicode transliteration
    assert normalize_filename("éxámple vídéo.mp4") == "example_video.mp4"

    # Edge cases: empty stem or special symbols only
    assert normalize_filename(".mp4") == "video.mp4"
    assert normalize_filename("   .mov") == "video.mov"
    assert normalize_filename("###$$$@@@.mkv") == "video.mkv"
    assert normalize_filename("already_clean_name.mp4") == "already_clean_name.mp4"

    # Preserves extension case as lowercase
    assert normalize_filename("TEST_CLIP.MP4") == "test_clip.mp4"


def test_resolve_unique_input_path(tmp_path: Path):
    date_dir = tmp_path / "2026-10-24"
    date_dir.mkdir(parents=True)

    # First attempt: file does not exist
    path_1 = resolve_unique_input_path(date_dir, "clip.mp4")
    assert path_1 == date_dir / "clip.mp4"

    # Simulate path_1 existing
    path_1.write_text("dummy")
    path_2 = resolve_unique_input_path(date_dir, "clip.mp4")
    assert path_2 == date_dir / "clip_2.mp4"

    # Simulate path_2 existing
    path_2.write_text("dummy 2")
    path_3 = resolve_unique_input_path(date_dir, "clip.mp4")
    assert path_3 == date_dir / "clip_3.mp4"


def test_compute_file_sha256(tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("AI Video Clipper Test Content", encoding="utf-8")
    hash_val = compute_file_sha256(test_file)
    assert isinstance(hash_val, str)
    assert len(hash_val) == 64
    # Re-computing on same content yields identical hash
    assert compute_file_sha256(test_file) == hash_val


def test_ingest_source_video_lifecycle(tmp_path: Path):
    input_root = tmp_path / "managed_inputs"
    source_file = tmp_path / "Jimmy Fallon & Anne Hathaway Interview.MP4"
    source_file.write_text("mock video content for hash calculation", encoding="utf-8")

    fixed_date = datetime.date(2026, 10, 24)
    dest_path, metadata = ingest_source_video(
        source_path=source_file,
        input_root=input_root,
        date=fixed_date,
        copy_file=True,
    )

    # Verifications
    assert dest_path.exists()
    assert dest_path.name == "jimmy_fallon_anne_hathaway_interview.mp4"
    assert dest_path.parent.name == "2026-10-24"
    assert metadata.schema_version == "v1.0"
    assert not metadata.video_id.startswith("vid_")
    assert uuid.UUID(metadata.video_id)
    assert metadata.original_filename == "Jimmy Fallon & Anne Hathaway Interview.MP4"
    assert metadata.stored_filename == "jimmy_fallon_anne_hathaway_interview.mp4"
    assert metadata.ingestion_date == "2026-10-24"
    assert metadata.media_type == "mp4"
    assert metadata.file_size_bytes == source_file.stat().st_size
    assert len(metadata.content_sha256) == 64

    # Metadata file alongside
    metadata_file = dest_path.with_name(f"{dest_path.stem}__metadata.json")
    assert metadata_file.exists()
    loaded_meta = load_ingestion_metadata(metadata_file)
    assert loaded_meta.video_id == metadata.video_id
    assert loaded_meta.content_sha256 == metadata.content_sha256


def test_ingest_source_video_collision_protection(tmp_path: Path):
    input_root = tmp_path / "inputs"
    fixed_date = datetime.date(2026, 10, 24)

    src1 = tmp_path / "interview.mp4"
    src1.write_text("file 1 content", encoding="utf-8")
    dest1, meta1 = ingest_source_video(src1, input_root=input_root, date=fixed_date)
    assert dest1.name == "interview.mp4"

    src2 = tmp_path / "INTERVIEW.MP4"
    src2.write_text("file 2 content", encoding="utf-8")
    dest2, meta2 = ingest_source_video(src2, input_root=input_root, date=fixed_date)
    assert dest2.name == "interview_2.mp4"
    assert dest1.exists()
    assert dest2.exists()
    assert dest1.read_text() == "file 1 content"
    assert dest2.read_text() == "file 2 content"


def test_ingest_source_video_no_copy_and_probe_handling(tmp_path: Path):
    input_root = tmp_path / "inputs"
    src = tmp_path / "text_sample.mp4"
    src.write_text("not a real mp4 video", encoding="utf-8")

    dest, meta = ingest_source_video(
        source_path=src,
        input_root=input_root,
        copy_file=False,
    )
    # When copy_file=False, destination path is resolved but file is not copied
    assert not dest.exists()
    assert meta.file_size_bytes == src.stat().st_size
    assert meta.original_filename == "text_sample.mp4"
    assert meta.stored_filename == "text_sample.mp4"
    # Probing fails gracefully on text file
    assert meta.probe_status in ("failed", "skipped")


def test_ingest_source_video_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ingest_source_video(Path("non_existent_video_path.mp4"))

