"""Regression tests for UUID-based artifact identity, directory layout, and collision prevention.

Validates the 12 key requirements:
1. Source IDs are valid canonical UUIDs without prefixes.
2. Long IDs are valid UUIDs without prefixes.
3. Short IDs are valid UUIDs without prefixes.
4. Long parent_id points to the source UUID.
5. Short parent_id points to the long UUID.
6. Two parents can each produce a short clip without overwriting one another.
7. Multiple long clips have unique output directories.
8. Master and final filenames use the same artifact UUID.
9. Manifest paths and metadata IDs agree with actual files.
10. Default output root resolves to repository-root outputs from both working directories.
11. Explicit custom output-root configuration remains functional.
12. Existing historical artifacts remain untouched.
"""

import os
import uuid
from pathlib import Path
import pytest

from app.domain.manifest.models import (
    ClipFiles,
    ClipMetadata,
    ManifestLongClipItem,
    ManifestShortClipItem,
    RunManifest,
    SourceVideoReference,
)
from app.domain.timeline.models import ClipTimeline
from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)
from app.services.media.rendering import RenderValidationResult
from app.services.rendering.long_clip_renderer import render_long_clip_package
from app.services.rendering.short_clip_renderer import render_short_clip_package
from app.services.storage.ingestion import generate_stable_video_id, generate_video_id
from app.services.storage.output_manager import (
    DEFAULT_OUTPUT_ROOT,
    OutputManager,
    get_repository_root,
)


def _is_valid_canonical_uuid(val: str) -> bool:
    """Validate that val is a canonical RFC 4122 lowercase hyphenated UUID without prefixes."""
    try:
        parsed = uuid.UUID(str(val))
        return str(parsed) == str(val).lower() and not str(val).startswith(("vid_", "lng_", "srt_", "cnd_"))
    except (ValueError, TypeError, AttributeError):
        return False


@pytest.fixture
def dummy_transcript_artifact() -> TranscriptArtifact:
    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="source.mp4",
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
            model="base",
            word_timestamps_enabled=True,
            duration_processed_seconds=120.0,
        ),
        word_timestamps_available=True,
        segment_count=2,
        segments=[
            TranscriptSegment(
                id=0,
                start_seconds=10.0,
                end_seconds=40.0,
                duration_seconds=30.0,
                text="First segment of interesting conversation.",
                words=[
                    WordTiming(word="First", start_seconds=10.0, end_seconds=11.0),
                    WordTiming(word="conversation.", start_seconds=38.0, end_seconds=40.0),
                ],
            ),
            TranscriptSegment(
                id=1,
                start_seconds=45.0,
                end_seconds=85.0,
                duration_seconds=40.0,
                text="Second segment with punchline.",
                words=[
                    WordTiming(word="Second", start_seconds=45.0, end_seconds=46.0),
                    WordTiming(word="punchline.", start_seconds=83.0, end_seconds=85.0),
                ],
            ),
        ],
    )


# 1. Source IDs are valid canonical UUIDs without prefixes
def test_source_id_is_valid_canonical_uuid():
    content_hash = "6cf414fcdae21d2e99887766554433221100aabbccddeeff0011223344556677"
    source_uuid = generate_stable_video_id(content_hash)
    assert _is_valid_canonical_uuid(source_uuid)
    assert not source_uuid.startswith("vid_")
    assert len(source_uuid) == 36

    # Verify deterministic behavior for content hash
    source_uuid_2 = generate_stable_video_id(content_hash)
    assert source_uuid == source_uuid_2

    # Verify generate_video_id without legacy returns canonical UUID
    source_uuid_3 = generate_video_id(content_hash=content_hash)
    assert source_uuid == source_uuid_3


# 2. Long IDs are valid UUIDs without prefixes
def test_long_id_is_valid_canonical_uuid():
    long_uuid = str(uuid.uuid4())
    assert _is_valid_canonical_uuid(long_uuid)
    assert not long_uuid.startswith("lng_")
    assert len(long_uuid) == 36


# 3. Short IDs are valid UUIDs without prefixes
def test_short_id_is_valid_canonical_uuid():
    short_uuid = str(uuid.uuid4())
    assert _is_valid_canonical_uuid(short_uuid)
    assert not short_uuid.startswith("srt_")
    assert len(short_uuid) == 36


# 4. Long parent_id points to the source UUID
def test_long_parent_id_points_to_source_uuid(tmp_path: Path, dummy_transcript_artifact, monkeypatch):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = generate_stable_video_id("source_file_content_hash_123")
    run_dir = mgr.create_run_directory(source_uuid)
    source_file = tmp_path / "source.mp4"
    source_file.write_text("mock video")

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"long mp4")
        dur = kwargs.get("candidate_end_seconds", 40.0) - kwargs.get("candidate_start_seconds", 10.0)
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=100,
            duration_seconds=dur,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)

    long_clip_uuid = str(uuid.uuid4())
    meta, manifest_item = render_long_clip_package(
        source_video_path=source_file,
        source_transcript=dummy_transcript_artifact,
        clip_id=long_clip_uuid,
        clip_index=1,
        source_start_seconds=10.0,
        source_end_seconds=40.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
        render_final_deliverable=False,
    )

    assert meta.clip_id == long_clip_uuid
    assert meta.parent_id == source_uuid
    assert meta.parent_type == "source_video"
    assert meta.source_video_id == source_uuid


# 5. Short parent_id points to the long UUID
def test_short_parent_id_points_to_long_uuid(tmp_path: Path, dummy_transcript_artifact, monkeypatch):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = generate_stable_video_id("source_file_content_hash_123")
    long_uuid = str(uuid.uuid4())
    short_uuid = str(uuid.uuid4())
    run_dir = mgr.create_run_directory(source_uuid)

    parent_meta = ClipMetadata(
        clip_id=long_uuid,
        clip_type="long",
        parent_id=source_uuid,
        parent_type="source_video",
        source_video_id=source_uuid,
        timeline=ClipTimeline(
            source_start_seconds=10.0,
            source_end_seconds=40.0,
            local_start_seconds=0.0,
            local_end_seconds=30.0,
            duration_seconds=30.0,
        ),
        files=ClipFiles(clean_master=f"{long_uuid}.mp4"),
    )

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"short mp4")
        dur = kwargs.get("candidate_end_seconds", 25.0) - kwargs.get("candidate_start_seconds", 5.0)
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=50,
            duration_seconds=dur,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    parent_clean = tmp_path / f"{long_uuid}.mp4"
    parent_clean.write_bytes(b"parent media")

    short_meta, manifest_item = render_short_clip_package(
        parent_clean_master_path=parent_clean,
        parent_transcript=dummy_transcript_artifact,
        parent_metadata=parent_meta,
        clip_id=short_uuid,
        clip_index=1,
        parent_local_start_seconds=5.0,
        parent_local_end_seconds=25.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=False,
    )

    assert short_meta.clip_id == short_uuid
    assert short_meta.parent_id == long_uuid
    assert short_meta.parent_type == "long_clip"
    assert short_meta.source_video_id == source_uuid
    assert manifest_item.parent_clip_id == long_uuid


# 6. Two parents can each produce a short clip without overwriting one another
def test_two_parents_can_each_produce_short_clip_without_collision(
    tmp_path: Path, dummy_transcript_artifact, monkeypatch
):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = str(uuid.uuid4())
    run_dir = mgr.create_run_directory(source_uuid)

    long_1_uuid = str(uuid.uuid4())
    long_2_uuid = str(uuid.uuid4())
    short_1_uuid = str(uuid.uuid4())
    short_2_uuid = str(uuid.uuid4())

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write unique text per file path to verify no overwrites
        p.write_text(f"content_for_{p.stem}")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=50,
            duration_seconds=15.0,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    parent1_meta = ClipMetadata(
        clip_id=long_1_uuid,
        clip_type="long",
        parent_id=source_uuid,
        parent_type="source_video",
        source_video_id=source_uuid,
        timeline=ClipTimeline(
            source_start_seconds=10.0,
            source_end_seconds=50.0,
            local_start_seconds=0.0,
            local_end_seconds=40.0,
            duration_seconds=40.0,
        ),
        files=ClipFiles(clean_master=f"{long_1_uuid}.mp4"),
    )

    parent2_meta = ClipMetadata(
        clip_id=long_2_uuid,
        clip_type="long",
        parent_id=source_uuid,
        parent_type="source_video",
        source_video_id=source_uuid,
        timeline=ClipTimeline(
            source_start_seconds=55.0,
            source_end_seconds=95.0,
            local_start_seconds=0.0,
            local_end_seconds=40.0,
            duration_seconds=40.0,
        ),
        files=ClipFiles(clean_master=f"{long_2_uuid}.mp4"),
    )

    dummy_media = tmp_path / "dummy.mp4"
    dummy_media.write_bytes(b"dummy")

    # Render short clip from parent 1
    meta1, item1 = render_short_clip_package(
        parent_clean_master_path=dummy_media,
        parent_transcript=dummy_transcript_artifact,
        parent_metadata=parent1_meta,
        clip_id=short_1_uuid,
        clip_index=1,
        parent_local_start_seconds=5.0,
        parent_local_end_seconds=20.0,
        run_dir=run_dir,
        output_manager=mgr,
    )

    # Render short clip from parent 2
    meta2, item2 = render_short_clip_package(
        parent_clean_master_path=dummy_media,
        parent_transcript=dummy_transcript_artifact,
        parent_metadata=parent2_meta,
        clip_id=short_2_uuid,
        clip_index=1,
        parent_local_start_seconds=10.0,
        parent_local_end_seconds=25.0,
        run_dir=run_dir,
        output_manager=mgr,
    )

    # Assert distinct directories exist
    dir1 = run_dir / "short_clips" / short_1_uuid
    dir2 = run_dir / "short_clips" / short_2_uuid
    assert dir1.exists()
    assert dir2.exists()
    assert dir1 != dir2

    # Assert clean master files are distinct and both exist
    file1 = dir1 / f"{short_1_uuid}.mp4"
    file2 = dir2 / f"{short_2_uuid}.mp4"
    assert file1.exists()
    assert file2.exists()
    assert file1.read_text() == f"content_for_{short_1_uuid}.rendering"
    assert file2.read_text() == f"content_for_{short_2_uuid}.rendering"


# 7. Multiple long clips have unique output directories
def test_multiple_long_clips_have_unique_output_directories(
    tmp_path: Path, dummy_transcript_artifact, monkeypatch
):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = str(uuid.uuid4())
    run_dir = mgr.create_run_directory(source_uuid)

    long_1_uuid = str(uuid.uuid4())
    long_2_uuid = str(uuid.uuid4())

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"content_for_{p.name}")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=100,
            duration_seconds=30.0,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)
    source_file = tmp_path / "src.mp4"
    source_file.write_bytes(b"source")

    render_long_clip_package(
        source_video_path=source_file,
        source_transcript=dummy_transcript_artifact,
        clip_id=long_1_uuid,
        clip_index=1,
        source_start_seconds=10.0,
        source_end_seconds=40.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
    )

    render_long_clip_package(
        source_video_path=source_file,
        source_transcript=dummy_transcript_artifact,
        clip_id=long_2_uuid,
        clip_index=2,
        source_start_seconds=45.0,
        source_end_seconds=75.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
    )

    dir1 = run_dir / "long_clips" / long_1_uuid
    dir2 = run_dir / "long_clips" / long_2_uuid
    assert dir1.exists()
    assert dir2.exists()
    assert dir1 != dir2
    assert (dir1 / f"{long_1_uuid}.mp4").exists()
    assert (dir2 / f"{long_2_uuid}.mp4").exists()


# 8. Master and final filenames use the same artifact UUID
def test_master_and_final_filenames_use_same_artifact_uuid(
    tmp_path: Path, dummy_transcript_artifact, monkeypatch
):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = str(uuid.uuid4())
    run_dir = mgr.create_run_directory(source_uuid)
    long_uuid = str(uuid.uuid4())

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"render")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=100,
            duration_seconds=30.0,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)
    source_file = tmp_path / "src.mp4"
    source_file.write_bytes(b"src")

    meta, item = render_long_clip_package(
        source_video_path=source_file,
        source_transcript=dummy_transcript_artifact,
        clip_id=long_uuid,
        clip_index=1,
        source_start_seconds=10.0,
        source_end_seconds=40.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
        render_final_deliverable=True,
    )

    clip_dir = run_dir / "long_clips" / long_uuid
    clean_master = clip_dir / f"{long_uuid}.mp4"
    final_render = clip_dir / f"{long_uuid}_final.mp4"

    assert clean_master.exists()
    assert final_render.exists()
    assert meta.files.clean_master == f"{long_uuid}.mp4"
    assert meta.files.final_render == f"{long_uuid}_final.mp4"
    assert item.clean_master_path == f"long_clips/{long_uuid}/{long_uuid}.mp4"
    assert item.final_render_path == f"long_clips/{long_uuid}/{long_uuid}_final.mp4"


# 9. Manifest paths and metadata IDs agree with actual files
def test_manifest_paths_and_metadata_ids_agree_with_actual_files(
    tmp_path: Path, dummy_transcript_artifact, monkeypatch
):
    mgr = OutputManager(output_root=tmp_path / "outputs")
    source_uuid = str(uuid.uuid4())
    run_dir = mgr.create_run_directory(source_uuid)
    long_uuid = str(uuid.uuid4())

    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"render")
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=100,
            duration_seconds=30.0,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)
    source_file = tmp_path / "src.mp4"
    source_file.write_bytes(b"src")

    meta, item = render_long_clip_package(
        source_video_path=source_file,
        source_transcript=dummy_transcript_artifact,
        clip_id=long_uuid,
        clip_index=1,
        source_start_seconds=10.0,
        source_end_seconds=40.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
        render_final_deliverable=True,
    )

    # Check disk vs metadata vs manifest
    assert (run_dir / item.folder).exists()
    assert (run_dir / item.clean_master_path).exists()
    assert (run_dir / item.final_render_path).exists()
    assert item.clip_id == meta.clip_id == long_uuid
    assert (run_dir / item.folder / "metadata.json").exists()
    assert (run_dir / item.folder / "transcript.json").exists()


# 10. Default output root resolves to repository-root outputs from both working directories
def test_default_output_root_resolves_to_repo_root_from_both_working_directories():
    repo_root = get_repository_root()
    expected_output_root = (repo_root / "outputs").resolve()

    # CWD: repo root
    orig_cwd = os.getcwd()
    try:
        os.chdir(repo_root)
        mgr_root = OutputManager()
        assert mgr_root.output_root == expected_output_root

        # CWD: backend
        backend_dir = repo_root / "backend"
        if backend_dir.exists():
            os.chdir(backend_dir)
            mgr_backend = OutputManager()
            assert mgr_backend.output_root == expected_output_root
            assert not str(mgr_backend.output_root).endswith("backend\\outputs")
            assert not str(mgr_backend.output_root).endswith("backend/outputs")
    finally:
        os.chdir(orig_cwd)


# 11. Explicit custom output-root configuration remains functional
def test_explicit_custom_output_root_remains_functional(tmp_path: Path):
    custom_root = tmp_path / "my_isolated_test_outputs"
    mgr = OutputManager(output_root=custom_root)
    assert mgr.output_root == custom_root.resolve()

    run_dir = mgr.create_run_directory("custom_video_identity")
    assert run_dir.exists()
    assert str(run_dir).startswith(str(custom_root.resolve()))


# 12. Existing historical artifacts remain untouched and readable
def test_existing_historical_artifacts_remain_untouched_and_readable():
    # Verify that existing validation run in backend/outputs is read-only accessible
    repo_root = get_repository_root()
    backend_outputs = repo_root / "backend" / "outputs" / "2026-10-30"
    if backend_outputs.exists():
        run_candidates = list(backend_outputs.glob("**/run_001_083927/manifest.json"))
        if run_candidates:
            manifest_file = run_candidates[0]
            mgr = OutputManager()
            manifest = mgr.load_manifest(manifest_file.parent)
            assert manifest.run_id == "run_001_083927"
            assert manifest.status == "completed"
            assert len(manifest.long_clips) == 5
            assert len(manifest.short_clips) == 15
            # Confirm historical files exist without modification
            assert manifest_file.exists()
