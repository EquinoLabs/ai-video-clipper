"""Long-clip rendering service for clean masters and deliverable packaging."""

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.domain.manifest.models import ClipFiles, ClipMetadata, ManifestLongClipItem
from app.domain.rendering.models import CaptionConfig, FramingConfig, OutputConfig, RenderValidationResult
from app.domain.timeline.models import ClipTimeline
from app.domain.transcript.models import TranscriptArtifact
from app.services.media.rendering import RenderError, render_candidate_clip
from app.services.storage.output_manager import OutputManager
from app.services.transcription.slicing import slice_transcript_for_long_clip

logger = logging.getLogger(__name__)


def render_long_clip_package(
    source_video_path: Path,
    source_transcript: TranscriptArtifact,
    clip_id: str,
    clip_index: int,
    source_start_seconds: float,
    source_end_seconds: float,
    run_dir: Path,
    source_video_id: str,
    output_manager: Optional[OutputManager] = None,
    render_final_deliverable: bool = False,
    framing_config: Optional[FramingConfig] = None,
    caption_config: Optional[CaptionConfig] = None,
    output_config: Optional[OutputConfig] = None,
    hook: Optional[str] = None,
    score: Optional[float] = None,
) -> Tuple[ClipMetadata, ManifestLongClipItem]:
    """Render and package a long clip according to the approved Stage 2 architecture contract.

    Artifacts generated inside run_dir/long_clips/clip_XX/:
    1. clip_XX.mp4: Clean master video (9:16 vertical center-crop, burn_subtitles=False).
    2. transcript.json: Sliced long-local transcript with preserved word timings.
    3. metadata.json: Typed ClipMetadata with explicit source and local timeline coordinates.
    4. Optional clip_XX_final.mp4: Burned subtitle deliverable if render_final_deliverable=True.
    """
    mgr = output_manager or OutputManager()
    long_clip_dir = mgr.get_long_clip_dir(run_dir, clip_id)
    long_clip_dir.mkdir(parents=True, exist_ok=True)

    clean_master_filename = f"{clip_id}.mp4"
    clean_master_path = long_clip_dir / clean_master_filename

    # Derive sliced transcript
    sliced_transcript = slice_transcript_for_long_clip(
        source_artifact=source_transcript,
        clip_start_seconds=source_start_seconds,
        clip_end_seconds=source_end_seconds,
        clip_id=clip_id,
    )
    transcript_path = long_clip_dir / "transcript.json"
    mgr.write_json_atomic(transcript_path, sliced_transcript)

    # Render clean master (burn_subtitles=False)
    with mgr.stage_media_path(clean_master_path) as staging_clean_path:
        render_res = render_candidate_clip(
            source_video_path=source_video_path,
            candidate_start_seconds=source_start_seconds,
            candidate_end_seconds=source_end_seconds,
            output_mp4_path=staging_clean_path,
            transcript_segments=source_transcript.segments,
            burn_subtitles=False,
            framing_config=framing_config,
            output_config=output_config,
        )
        if not render_res.is_valid:
            raise RenderError(f"Clean master rendering failed validation: {render_res.validation_errors}")

    final_render_path_str: Optional[str] = None
    files = ClipFiles(
        clean_master=clean_master_filename,
        transcript="transcript.json",
    )

    # Optional final deliverable render (burned subtitles)
    if render_final_deliverable:
        final_filename = f"{clip_id}_final.mp4"
        final_deliverable_path = long_clip_dir / final_filename
        with mgr.stage_media_path(final_deliverable_path) as staging_final_path:
            render_final_res = render_candidate_clip(
                source_video_path=source_video_path,
                candidate_start_seconds=source_start_seconds,
                candidate_end_seconds=source_end_seconds,
                output_mp4_path=staging_final_path,
                transcript_segments=source_transcript.segments,
                burn_subtitles=True,
                framing_config=framing_config,
                caption_config=caption_config,
                output_config=output_config,
            )
            if not render_final_res.is_valid:
                raise RenderError(f"Final deliverable rendering failed validation: {render_final_res.validation_errors}")
            # Promote generated subtitles to canonical location
            staging_ass = staging_final_path.with_suffix(".ass")
            if staging_ass.exists():
                import os
                os.replace(staging_ass, long_clip_dir / "captions.ass")
            staging_srt = staging_final_path.with_suffix(".srt")
            if staging_srt.exists():
                import os
                os.replace(staging_srt, long_clip_dir / "captions.srt")
        files.final_render = final_filename
        files.captions_ass = "captions.ass"
        files.captions_srt = "captions.srt"
        final_render_path_str = f"long_clips/{clip_id}/{final_filename}"

    duration_sec = round(source_end_seconds - source_start_seconds, 3)

    # Construct ClipMetadata
    timeline = ClipTimeline(
        source_start_seconds=source_start_seconds,
        source_end_seconds=source_end_seconds,
        local_start_seconds=0.0,
        local_end_seconds=duration_sec,
        duration_seconds=duration_sec,
    )

    status_str = "final_render_ready" if render_final_deliverable else "clean_master_ready"

    clip_metadata = ClipMetadata(
        clip_id=clip_id,
        clip_type="long",
        parent_id=source_video_id,
        parent_type="source_video",
        source_video_id=source_video_id,
        timeline=timeline,
        hook=hook,
        overall_score=score,
        status=status_str,
        files=files,
    )
    mgr.save_clip_metadata(long_clip_dir, clip_metadata)

    # Construct ManifestLongClipItem
    manifest_item = ManifestLongClipItem(
        clip_id=clip_id,
        folder=f"long_clips/{clip_id}",
        source_start_seconds=source_start_seconds,
        source_end_seconds=source_end_seconds,
        duration_seconds=duration_sec,
        score=score,
        status=status_str,
        clean_master_path=f"long_clips/{clip_id}/{clean_master_filename}",
        final_render_path=final_render_path_str,
        short_clips_count=0,
    )

    return clip_metadata, manifest_item
