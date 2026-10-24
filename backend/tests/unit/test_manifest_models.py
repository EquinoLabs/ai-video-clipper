"""Unit tests for RunManifest and ClipMetadata models and OutputManager manifest persistence."""

from pathlib import Path
from pydantic import ValidationError
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
from app.services.storage.output_manager import OutputManager


def test_run_manifest_roundtrip_and_defaults():
    manifest = RunManifest(
        run_id="run_20261024_210000_001",
        timezone="Asia/Kolkata",
        pipeline_mode="full",
        status="running",
        source_video=SourceVideoReference(
            video_id="vid_20261024_01",
            normalized_name="anne_hathaway_tonight_show",
            source_path="input/2026-10-24/anne_hathaway_tonight_show.mp4",
            duration_seconds=622.84,
        ),
        configuration={"editorial_goal": "humor", "caption_preset": "default_bold_v1"},
        stage_statuses={"transcription": "completed", "long_discovery": "completed"},
        long_clips=[
            ManifestLongClipItem(
                clip_id="lng_001",
                folder="long_clips/clip_01",
                source_start_seconds=11.73,
                source_end_seconds=63.00,
                duration_seconds=51.27,
                score=88.5,
                status="clean_master_ready",
                clean_master_path="long_clips/clip_01/clip_01.mp4",
                short_clips_count=1,
            )
        ],
        short_clips=[
            ManifestShortClipItem(
                clip_id="srt_001",
                parent_clip_id="lng_001",
                folder="short_clips/clip_01",
                source_start_seconds=45.00,
                source_end_seconds=63.00,
                parent_local_start_seconds=33.27,
                parent_local_end_seconds=51.27,
                duration_seconds=18.00,
                score=92.0,
                status="clean_master_ready",
                clean_master_path="short_clips/clip_01/clip_01.mp4",
            )
        ],
    )

    # Serialization and Deserialization
    json_str = manifest.model_dump_json(indent=2)
    deserialized = RunManifest.model_validate_json(json_str)

    assert deserialized.schema_version == "v1.0"
    assert deserialized.run_id == "run_20261024_210000_001"
    assert deserialized.timezone == "Asia/Kolkata"
    assert deserialized.source_video.video_id == "vid_20261024_01"
    assert len(deserialized.long_clips) == 1
    assert deserialized.long_clips[0].clip_id == "lng_001"
    assert len(deserialized.short_clips) == 1
    assert deserialized.short_clips[0].parent_clip_id == "lng_001"


def test_clip_metadata_roundtrip():
    # Long clip metadata
    long_meta = ClipMetadata(
        clip_id="lng_001",
        clip_type="long",
        parent_id="vid_20261024_01",
        parent_type="source_video",
        source_video_id="vid_20261024_01",
        timeline=ClipTimeline(
            source_start_seconds=11.73,
            source_end_seconds=63.00,
            local_start_seconds=0.0,
            local_end_seconds=51.27,
            duration_seconds=51.27,
        ),
        hook="Jimmy competing against his kids",
        overall_score=88.5,
        score_breakdown={"hook_strength": 4.5, "completeness_coherence": 4.8},
        status="clean_master_ready",
        files=ClipFiles(
            clean_master="clip_01.mp4",
            final_render="clip_01_final.mp4",
            transcript="transcript.json",
        ),
    )
    long_json = long_meta.model_dump_json()
    long_loaded = ClipMetadata.model_validate_json(long_json)
    assert long_loaded.clip_id == "lng_001"
    assert long_loaded.clip_type == "long"
    assert long_loaded.parent_type == "source_video"
    assert long_loaded.timeline.duration_seconds == 51.27

    # Short clip metadata with long parent
    short_meta = ClipMetadata(
        clip_id="srt_001",
        clip_type="short",
        parent_id="lng_001",
        parent_type="long_clip",
        source_video_id="vid_20261024_01",
        timeline=ClipTimeline(
            source_start_seconds=45.00,
            source_end_seconds=63.00,
            local_start_seconds=33.27,
            local_end_seconds=51.27,
            duration_seconds=18.00,
        ),
        hook="I play for money too",
        overall_score=92.0,
        status="clean_master_ready",
        files=ClipFiles(
            clean_master="clip_01.mp4",
            transcript="transcript.json",
            captions_ass="captions.ass",
        ),
    )
    short_json = short_meta.model_dump_json()
    short_loaded = ClipMetadata.model_validate_json(short_json)
    assert short_loaded.clip_id == "srt_001"
    assert short_loaded.clip_type == "short"
    assert short_loaded.parent_id == "lng_001"
    assert short_loaded.parent_type == "long_clip"


def test_output_manager_manifest_and_metadata_persistence(tmp_path: Path):
    mgr = OutputManager(output_root=tmp_path)
    run_dir = mgr.create_run_directory("anne_hathaway")
    clip_dir = mgr.get_long_clip_dir(run_dir, 1)

    manifest = RunManifest(
        run_id="run_test_001",
        source_video=SourceVideoReference(
            video_id="vid_test_01",
            normalized_name="anne_hathaway",
            source_path="input/2026-10-24/anne_hathaway.mp4",
            duration_seconds=100.0,
        ),
    )
    manifest_file = mgr.save_manifest(run_dir, manifest)
    assert manifest_file.exists()
    loaded_manifest = mgr.load_manifest(run_dir)
    assert loaded_manifest.run_id == "run_test_001"

    clip_meta = ClipMetadata(
        clip_id="lng_001",
        clip_type="long",
        parent_type="source_video",
        source_video_id="vid_test_01",
        timeline=ClipTimeline(
            source_start_seconds=10.0,
            source_end_seconds=50.0,
            local_start_seconds=0.0,
            local_end_seconds=40.0,
            duration_seconds=40.0,
        ),
    )
    meta_file = mgr.save_clip_metadata(clip_dir, clip_meta)
    assert meta_file.exists()
    loaded_meta = mgr.load_clip_metadata(clip_dir)
    assert loaded_meta.clip_id == "lng_001"


def test_manifest_and_clip_invalid_status_raises():
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="run_001",
            status="invalid_status",  # type: ignore
            source_video=SourceVideoReference(
                video_id="vid_001",
                normalized_name="sample",
                source_path="input/2026-10-24/sample.mp4",
                duration_seconds=10.0,
            ),
        )

    with pytest.raises(ValidationError):
        ClipMetadata(
            clip_id="lng_001",
            clip_type="long",
            parent_type="invalid_parent",  # type: ignore
            source_video_id="vid_001",
            timeline=ClipTimeline(
                source_start_seconds=0.0,
                source_end_seconds=10.0,
                local_start_seconds=0.0,
                local_end_seconds=10.0,
                duration_seconds=10.0,
            ),
        )


def test_clip_metadata_lineage_validation():
    timeline = ClipTimeline(
        source_start_seconds=10.0,
        source_end_seconds=30.0,
        local_start_seconds=0.0,
        local_end_seconds=20.0,
        duration_seconds=20.0,
    )

    # 1. Valid long clip with matching parent_id
    long_valid_1 = ClipMetadata(
        clip_id="lng_001",
        clip_type="long",
        parent_id="vid_001",
        parent_type="source_video",
        source_video_id="vid_001",
        timeline=timeline,
    )
    assert long_valid_1.parent_id == "vid_001"
    assert long_valid_1.parent_type == "source_video"

    # 2. Valid long clip with parent_id omitted (auto-populated to source_video_id)
    long_valid_2 = ClipMetadata(
        clip_id="lng_002",
        clip_type="long",
        parent_type="source_video",
        source_video_id="vid_001",
        timeline=timeline,
    )
    assert long_valid_2.parent_id == "vid_001"

    # 3. Invalid long clip referencing long_clip parent_type
    with pytest.raises(ValidationError, match="Long clip .* must have parent_type='source_video'"):
        ClipMetadata(
            clip_id="lng_003",
            clip_type="long",
            parent_id="lng_parent",
            parent_type="long_clip",
            source_video_id="vid_001",
            timeline=timeline,
        )

    # 4. Invalid long clip with mismatched parent_id
    with pytest.raises(ValidationError, match="Long clip parent_id .* must match source_video_id"):
        ClipMetadata(
            clip_id="lng_004",
            clip_type="long",
            parent_id="vid_other",
            parent_type="source_video",
            source_video_id="vid_001",
            timeline=timeline,
        )

    # 5. Valid short clip referencing long_clip parent
    short_valid = ClipMetadata(
        clip_id="srt_001",
        clip_type="short",
        parent_id="lng_001",
        parent_type="long_clip",
        source_video_id="vid_001",
        timeline=timeline,
    )
    assert short_valid.clip_type == "short"
    assert short_valid.parent_type == "long_clip"
    assert short_valid.parent_id == "lng_001"

    # 6. Invalid short clip referencing source_video parent_type
    with pytest.raises(ValidationError, match="Short clip .* must have parent_type='long_clip'"):
        ClipMetadata(
            clip_id="srt_002",
            clip_type="short",
            parent_id="lng_001",
            parent_type="source_video",
            source_video_id="vid_001",
            timeline=timeline,
        )

    # 7. Invalid short clip with missing parent_id
    with pytest.raises(ValidationError, match="Short clip .* must have a valid non-empty parent_id"):
        ClipMetadata(
            clip_id="srt_003",
            clip_type="short",
            parent_id=None,
            parent_type="long_clip",
            source_video_id="vid_001",
            timeline=timeline,
        )

    # 8. Invalid short clip with whitespace parent_id
    with pytest.raises(ValidationError, match="Short clip .* must have a valid non-empty parent_id"):
        ClipMetadata(
            clip_id="srt_004",
            clip_type="short",
            parent_id="   ",
            parent_type="long_clip",
            source_video_id="vid_001",
            timeline=timeline,
        )


