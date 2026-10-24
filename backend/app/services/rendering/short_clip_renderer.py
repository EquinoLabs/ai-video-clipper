"""Short-clip rendering service for clean masters and deliverable packaging."""

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.domain.manifest.models import ClipFiles, ClipMetadata, ManifestShortClipItem
from app.domain.rendering.models import CaptionConfig, FramingConfig, OutputConfig, RenderValidationResult
from app.domain.timeline.models import ClipTimeline, parent_local_to_source
from app.domain.transcript.models import TranscriptArtifact
from app.services.media.rendering import RenderError, render_candidate_clip
from app.services.storage.output_manager import OutputManager
from app.services.transcription.slicing import slice_transcript_for_short_clip

logger = logging.getLogger(__name__)


def render_short_clip_package(
    parent_clean_master_path: Path,
    parent_transcript: TranscriptArtifact,
    parent_metadata: ClipMetadata,
    clip_id: str,
    clip_index: int,
    parent_local_start_seconds: float,
    parent_local_end_seconds: float,
    run_dir: Path,
    output_manager: Optional[OutputManager] = None,
    render_final_deliverable: bool = False,
    framing_config: Optional[FramingConfig] = None,
    caption_config: Optional[CaptionConfig] = None,
    output_config: Optional[OutputConfig] = None,
    hook: Optional[str] = None,
    score: Optional[float] = None,
) -> Tuple[ClipMetadata, ManifestShortClipItem]:
    """Render and package a short clip extracted directly from a clean long master.

    Strict Architectural Rules:
    1. parent_clean_master_path MUST be the clean long master (burn_subtitles=False). Never a final render.
    2. Input intervals (parent_local_start_seconds, parent_local_end_seconds) are in parent long clip coordinates.
    3. Source intervals are derived using parent_metadata.timeline.source_start_seconds.
    4. Slices long-clip transcript into a self-contained short-local transcript.json.
    5. Writes metadata.json enforcing parent_type='long_clip' and lineage validation.
    6. Uses atomic media and JSON staging to ensure no partial files are left on failure.
    """
    mgr = output_manager or OutputManager()
    short_clip_dir = mgr.get_short_clip_dir(run_dir, clip_index)
    short_clip_dir.mkdir(parents=True, exist_ok=True)

    clean_master_filename = f"clip_{clip_index:02d}.mp4"
    clean_master_path = short_clip_dir / clean_master_filename

    # Calculate absolute source timing coordinates
    parent_source_start = parent_metadata.timeline.source_start_seconds
    source_start_sec = parent_local_to_source(
        local_time=parent_local_start_seconds,
        parent_source_start=parent_source_start,
    )
    source_end_sec = parent_local_to_source(
        local_time=parent_local_end_seconds,
        parent_source_start=parent_source_start,
    )
    duration_sec = round(parent_local_end_seconds - parent_local_start_seconds, 3)

    # Derive sliced transcript for the short clip (0.0 to duration_sec)
    sliced_transcript = slice_transcript_for_short_clip(
        long_transcript=parent_transcript,
        short_local_start_seconds=parent_local_start_seconds,
        short_local_end_seconds=parent_local_end_seconds,
        clip_id=clip_id,
    )
    transcript_path = short_clip_dir / "transcript.json"
    mgr.write_json_atomic(transcript_path, sliced_transcript)

    # Render clean short master from clean long master (burn_subtitles=False)
    # The parent clean master is already 9:16 vertical, so framing is identity/passthrough or standard crop
    with mgr.stage_media_path(clean_master_path) as staging_clean_path:
        render_res = render_candidate_clip(
            source_video_path=parent_clean_master_path,
            candidate_start_seconds=parent_local_start_seconds,
            candidate_end_seconds=parent_local_end_seconds,
            output_mp4_path=staging_clean_path,
            transcript_segments=parent_transcript.segments,
            burn_subtitles=False,
            framing_config=framing_config,
            output_config=output_config,
        )
        if not render_res.is_valid:
            raise RenderError(f"Clean short master rendering failed validation: {render_res.validation_errors}")

    final_render_path_str: Optional[str] = None
    files = ClipFiles(
        clean_master=clean_master_filename,
        transcript="transcript.json",
    )

    # Optional final deliverable render (burned subtitles)
    if render_final_deliverable:
        final_filename = f"clip_{clip_index:02d}_final.mp4"
        final_deliverable_path = short_clip_dir / final_filename
        with mgr.stage_media_path(final_deliverable_path) as staging_final_path:
            render_final_res = render_candidate_clip(
                source_video_path=parent_clean_master_path,
                candidate_start_seconds=parent_local_start_seconds,
                candidate_end_seconds=parent_local_end_seconds,
                output_mp4_path=staging_final_path,
                transcript_segments=parent_transcript.segments,
                burn_subtitles=True,
                framing_config=framing_config,
                caption_config=caption_config,
                output_config=output_config,
            )
            if not render_final_res.is_valid:
                raise RenderError(f"Final short deliverable rendering failed validation: {render_final_res.validation_errors}")
        files.final_render = final_filename
        files.captions_ass = "captions.ass"
        files.captions_srt = "captions.srt"
        final_render_path_str = f"short_clips/clip_{clip_index:02d}/{final_filename}"

    # Construct ClipTimeline
    timeline = ClipTimeline(
        source_start_seconds=source_start_sec,
        source_end_seconds=source_end_sec,
        local_start_seconds=round(parent_local_start_seconds, 3),
        local_end_seconds=round(parent_local_end_seconds, 3),
        duration_seconds=duration_sec,
    )

    status_str = "final_render_ready" if render_final_deliverable else "clean_master_ready"

    # Construct ClipMetadata
    clip_metadata = ClipMetadata(
        clip_id=clip_id,
        clip_type="short",
        parent_id=parent_metadata.clip_id,
        parent_type="long_clip",
        source_video_id=parent_metadata.source_video_id,
        timeline=timeline,
        hook=hook,
        overall_score=score,
        status=status_str,
        files=files,
    )
    mgr.save_clip_metadata(short_clip_dir, clip_metadata)

    # Construct ManifestShortClipItem
    manifest_item = ManifestShortClipItem(
        clip_id=clip_id,
        parent_clip_id=parent_metadata.clip_id,
        folder=f"short_clips/clip_{clip_index:02d}",
        source_start_seconds=source_start_sec,
        source_end_seconds=source_end_sec,
        parent_local_start_seconds=round(parent_local_start_seconds, 3),
        parent_local_end_seconds=round(parent_local_end_seconds, 3),
        duration_seconds=duration_sec,
        score=score,
        status=status_str,
        clean_master_path=f"short_clips/clip_{clip_index:02d}/{clean_master_filename}",
        final_render_path=final_render_path_str,
    )

    return clip_metadata, manifest_item
