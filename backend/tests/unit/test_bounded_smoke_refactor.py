"""Bounded smoke test for UUID artifact refactor verification.

Simulates end-to-end multi-parent, multi-child artifact generation, directory structure,
and API loading without running a 20-minute FFmpeg/LLM pipeline.
"""

import json
import uuid
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

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
from app.main import app
from app.services.media.rendering import RenderValidationResult
from app.services.rendering.long_clip_renderer import render_long_clip_package
from app.services.rendering.short_clip_renderer import render_short_clip_package
from app.services.storage.ingestion import generate_stable_video_id
from app.services.storage.output_manager import OutputManager


@pytest.fixture
def smoke_transcript() -> TranscriptArtifact:
    segments = [
        TranscriptSegment(
            id=i,
            start_seconds=float(i * 10),
            end_seconds=float((i + 1) * 10),
            duration_seconds=10.0,
            text=f"Transcript utterance number {i}",
            words=[
                WordTiming(word=f"word_{i}_a", start_seconds=float(i * 10), end_seconds=float(i * 10 + 2)),
                WordTiming(word=f"word_{i}_b", start_seconds=float(i * 10 + 3), end_seconds=float((i + 1) * 10)),
            ],
        )
        for i in range(10)
    ]
    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="smoke_interview.mp4",
            format_name="mov,mp4",
            duration_seconds=100.0,
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
            model="base",
            word_timestamps_enabled=True,
            duration_processed_seconds=100.0,
        ),
        word_timestamps_available=True,
        segment_count=len(segments),
        segments=segments,
    )


@pytest.mark.asyncio
async def test_bounded_smoke_pipeline(tmp_path: Path, smoke_transcript, monkeypatch):
    """Execute complete smoke test verifying UUID identity, lineage, collision-prevention, and review loading."""
    smoke_output_root = tmp_path / "smoke_outputs"
    mgr = OutputManager(output_root=smoke_output_root)

    # 1. Source Identity
    content_hash = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    source_uuid = generate_stable_video_id(content_hash)
    assert uuid.UUID(source_uuid)
    assert not source_uuid.startswith("vid_")

    # 2. Run Directory in expected structure: <outputs>/<date>/<source_uuid>/<run_id>
    run_dir = mgr.create_run_directory(source_uuid)
    assert run_dir.exists()
    assert run_dir.parent.name == source_uuid
    run_id = run_dir.name

    # Mock FFmpeg renderer to produce valid simulated media files without external dependencies
    def mock_render(output_mp4_path, **kwargs):
        p = Path(output_mp4_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write unique bytes per file path
        p.write_text(f"simulated_mp4_content_for_{p.name}")
        dur = kwargs.get("candidate_end_seconds", 30.0) - kwargs.get("candidate_start_seconds", 0.0)
        return RenderValidationResult(
            is_valid=True,
            output_path=p,
            file_size_bytes=1024,
            duration_seconds=dur,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
        )

    monkeypatch.setattr("app.services.rendering.long_clip_renderer.render_candidate_clip", mock_render)
    monkeypatch.setattr("app.services.rendering.short_clip_renderer.render_candidate_clip", mock_render)

    source_video_file = tmp_path / "smoke_source.mp4"
    source_video_file.write_bytes(b"dummy source video")

    # 3. Render at least two Long Clips with different UUIDs
    long_1_uuid = str(uuid.uuid4())
    long_2_uuid = str(uuid.uuid4())
    assert long_1_uuid != long_2_uuid

    long_1_meta, long_1_item = render_long_clip_package(
        source_video_path=source_video_file,
        source_transcript=smoke_transcript,
        clip_id=long_1_uuid,
        clip_index=1,
        source_start_seconds=0.0,
        source_end_seconds=40.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
        render_final_deliverable=True,
        hook="Long hook 1",
        score=91.0,
    )

    long_2_meta, long_2_item = render_long_clip_package(
        source_video_path=source_video_file,
        source_transcript=smoke_transcript,
        clip_id=long_2_uuid,
        clip_index=2,
        source_start_seconds=45.0,
        source_end_seconds=85.0,
        run_dir=run_dir,
        source_video_id=source_uuid,
        output_manager=mgr,
        render_final_deliverable=True,
        hook="Long hook 2",
        score=87.0,
    )

    # Verify long clips directories and files
    assert (run_dir / "long_clips" / long_1_uuid / f"{long_1_uuid}.mp4").exists()
    assert (run_dir / "long_clips" / long_1_uuid / f"{long_1_uuid}_final.mp4").exists()
    assert (run_dir / "long_clips" / long_2_uuid / f"{long_2_uuid}.mp4").exists()
    assert (run_dir / "long_clips" / long_2_uuid / f"{long_2_uuid}_final.mp4").exists()

    # Verify long parent_id points to source_uuid
    assert long_1_meta.parent_id == source_uuid
    assert long_2_meta.parent_id == source_uuid
    assert long_1_meta.source_video_id == source_uuid
    assert long_2_meta.source_video_id == source_uuid

    # 4. Render multiple short clips from each long clip
    # Parent 1 children
    short_1a_uuid = str(uuid.uuid4())
    short_1b_uuid = str(uuid.uuid4())
    # Parent 2 children
    short_2a_uuid = str(uuid.uuid4())
    short_2b_uuid = str(uuid.uuid4())

    all_short_uuids = [short_1a_uuid, short_1b_uuid, short_2a_uuid, short_2b_uuid]
    assert len(set(all_short_uuids)) == 4, "Short UUIDs must all be mutually distinct"

    short_manifest_items = []

    # Render Short 1a from Long 1
    s1a_meta, s1a_item = render_short_clip_package(
        parent_clean_master_path=run_dir / "long_clips" / long_1_uuid / f"{long_1_uuid}.mp4",
        parent_transcript=smoke_transcript,
        parent_metadata=long_1_meta,
        clip_id=short_1a_uuid,
        clip_index=1,
        parent_local_start_seconds=5.0,
        parent_local_end_seconds=20.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=True,
    )
    short_manifest_items.append(s1a_item)

    # Render Short 1b from Long 1
    s1b_meta, s1b_item = render_short_clip_package(
        parent_clean_master_path=run_dir / "long_clips" / long_1_uuid / f"{long_1_uuid}.mp4",
        parent_transcript=smoke_transcript,
        parent_metadata=long_1_meta,
        clip_id=short_1b_uuid,
        clip_index=2,
        parent_local_start_seconds=22.0,
        parent_local_end_seconds=38.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=True,
    )
    short_manifest_items.append(s1b_item)

    # Render Short 2a from Long 2
    s2a_meta, s2a_item = render_short_clip_package(
        parent_clean_master_path=run_dir / "long_clips" / long_2_uuid / f"{long_2_uuid}.mp4",
        parent_transcript=smoke_transcript,
        parent_metadata=long_2_meta,
        clip_id=short_2a_uuid,
        clip_index=1,
        parent_local_start_seconds=5.0,
        parent_local_end_seconds=20.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=True,
    )
    short_manifest_items.append(s2a_item)

    # Render Short 2b from Long 2
    s2b_meta, s2b_item = render_short_clip_package(
        parent_clean_master_path=run_dir / "long_clips" / long_2_uuid / f"{long_2_uuid}.mp4",
        parent_transcript=smoke_transcript,
        parent_metadata=long_2_meta,
        clip_id=short_2b_uuid,
        clip_index=2,
        parent_local_start_seconds=22.0,
        parent_local_end_seconds=38.0,
        run_dir=run_dir,
        output_manager=mgr,
        render_final_deliverable=True,
    )
    short_manifest_items.append(s2b_item)

    # 5. Collision Prevention Verification: All 4 short clips exist in separate folders without collisions
    short_dirs = list((run_dir / "short_clips").iterdir())
    assert len(short_dirs) == 4, f"Expected 4 distinct short clip folders, found {len(short_dirs)}"
    for s_uuid in all_short_uuids:
        s_folder = run_dir / "short_clips" / s_uuid
        assert s_folder.exists(), f"Short clip folder missing: {s_folder}"
        assert (s_folder / f"{s_uuid}.mp4").exists(), f"Clean master missing: {s_uuid}.mp4"
        assert (s_folder / f"{s_uuid}_final.mp4").exists(), f"Final deliverable missing: {s_uuid}_final.mp4"
        assert (s_folder / "metadata.json").exists()
        assert (s_folder / "transcript.json").exists()

    # 6. Correct Lineage & Parent IDs
    assert s1a_meta.parent_id == long_1_uuid
    assert s1b_meta.parent_id == long_1_uuid
    assert s2a_meta.parent_id == long_2_uuid
    assert s2b_meta.parent_id == long_2_uuid

    for s_meta in [s1a_meta, s1b_meta, s2a_meta, s2b_meta]:
        assert s_meta.parent_type == "long_clip"
        assert s_meta.source_video_id == source_uuid

    # 7. Construct and Save RunManifest
    manifest = RunManifest(
        run_id=run_id,
        source_video=SourceVideoReference(
            video_id=source_uuid,
            normalized_name="smoke_interview",
            source_path="init_input/smoke_interview.mp4",
            duration_seconds=100.0,
        ),
        long_clips=[long_1_item, long_2_item],
        short_clips=short_manifest_items,
        status="completed",
    )
    manifest_file = mgr.save_manifest(run_dir, manifest)
    assert manifest_file.exists()

    # Verify loading through OutputManager
    loaded_manifest = mgr.load_manifest(run_dir)
    assert loaded_manifest.run_id == run_id
    assert loaded_manifest.source_video.video_id == source_uuid
    assert len(loaded_manifest.long_clips) == 2
    assert len(loaded_manifest.short_clips) == 4

    # Verify all manifest paths point to real files
    for lc in loaded_manifest.long_clips:
        assert (run_dir / lc.folder).is_dir()
        assert (run_dir / lc.clean_master_path).is_file()
        assert (run_dir / lc.final_render_path).is_file()

    for sc in loaded_manifest.short_clips:
        assert (run_dir / sc.folder).is_dir()
        assert (run_dir / sc.clean_master_path).is_file()
        assert (run_dir / sc.final_render_path).is_file()

    # 8. Verify Review API Loading
    monkeypatch.setattr("app.api.v1.routes.review.OUTPUTS_BASE_DIR", smoke_output_root)

    # Create dummy candidates.json for Review API compatibility check
    candidates_file = run_dir / "candidates.json"
    candidates_file.write_text(
        json.dumps(
            {
                "schema_version": "v1.0",
                "source_media": {
                    "filename": "smoke_interview.mp4",
                    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                    "duration_seconds": 100.0,
                    "size_bytes": 5000000,
                    "video_streams_count": 1,
                    "audio_streams_count": 1,
                    "selected_audio_stream_index": 0,
                    "audio_codec": "aac",
                    "audio_sample_rate": 44100,
                    "audio_channels": 2,
                },
                "generation": {
                    "editorial_goal": "overall",
                    "provider": "ollama",
                    "model": "qwen2.5:7b",
                    "settings": {
                        "min_duration_seconds": 10.0,
                        "preferred_min_seconds": 15.0,
                        "preferred_max_seconds": 45.0,
                        "target_duration_seconds": 30.0,
                        "max_duration_seconds": 60.0,
                        "candidate_pool_target": 4,
                        "display_limit": 4,
                    },
                },
                "candidates_count": 0,
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check listing runs
        res_list = await client.get("/api/v1/review/runs")
        assert res_list.status_code == 200
        runs_data = res_list.json()
        assert any(r["run_id"] == run_id for r in runs_data)

        # Check run details
        res_details = await client.get(f"/api/v1/review/runs/{run_id}")
        assert res_details.status_code == 200
        assert res_details.json()["summary"]["run_id"] == run_id

        # Check media access for long clip final deliverable
        res_media_long = await client.get(f"/api/v1/review/runs/{run_id}/media/{long_1_uuid}_final.mp4")
        assert res_media_long.status_code == 200

        # Check media access for short clip clean master
        res_media_short = await client.get(f"/api/v1/review/runs/{run_id}/media/{short_2b_uuid}.mp4")
        assert res_media_short.status_code == 200
