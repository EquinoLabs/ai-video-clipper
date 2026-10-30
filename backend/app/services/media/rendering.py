"""FFmpeg video trimming, 9:16 vertical center-crop framing, and subtitle burning service."""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from app.domain.rendering.models import (
    CaptionConfig,
    FramingConfig,
    FramingMode,
    OutputConfig,
    RenderValidationResult,
)
from app.domain.transcript.models import TranscriptSegment
from app.services.media.caption_styles import resolve_caption_config
from app.services.media.ffmpeg import check_ffmpeg_installed
from app.services.media.probing import probe_media_file
from app.services.media.subtitles import write_subtitles_for_candidate

logger = logging.getLogger(__name__)


class RenderError(Exception):
    """Exception raised when rendering fails."""
    pass


def build_center_crop_filter(
    source_width: int,
    source_height: int,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """Build FFmpeg crop filter for 9:16 vertical center-crop.

    Calculates the largest 9:16 box centered in source frame:
    crop_w = min(source_width, floor(source_height * 9 / 16))
    crop_h = floor(crop_w * 16 / 9)
    crop=w=crop_w:h=crop_h:x=(in_w-out_w)/2:y=(in_h-out_h)/2,scale=target_w:target_h
    """
    target_aspect = 9.0 / 16.0
    source_aspect = source_width / source_height

    if source_aspect >= target_aspect:
        # Source is wider than 9:16 (standard 16:9 landscape)
        crop_h = source_height
        crop_w = int(source_height * target_aspect)
    else:
        # Source is narrower than 9:16
        crop_w = source_width
        crop_h = int(source_width / target_aspect)

    # Ensure even dimensions for libx264
    crop_w = crop_w - (crop_w % 2)
    crop_h = crop_h - (crop_h % 2)

    return f"crop={crop_w}:{crop_h}:(in_w-out_w)/2:(in_h-out_h)/2,scale={target_width}:{target_height}"


def validate_rendered_output(
    output_path: Path,
    expected_duration: float,
    expected_width: int = 1080,
    expected_height: int = 1920,
    duration_tolerance: float = 1.0,
) -> RenderValidationResult:
    """Validate rendered MP4 file integrity, streams, duration, and resolution."""
    errors = []
    p = Path(output_path)
    if not p.exists() or p.stat().st_size == 0:
        return RenderValidationResult(
            is_valid=False,
            output_path=p,
            file_size_bytes=0,
            duration_seconds=0.0,
            width=0,
            height=0,
            video_codec="none",
            audio_codec="none",
            has_audio=False,
            validation_errors=["Output file does not exist or is empty."],
        )

    file_size = p.stat().st_size

    try:
        probe = probe_media_file(p)
    except Exception as exc:
        return RenderValidationResult(
            is_valid=False,
            output_path=p,
            file_size_bytes=file_size,
            duration_seconds=0.0,
            width=0,
            height=0,
            video_codec="unknown",
            audio_codec="unknown",
            has_audio=False,
            validation_errors=[f"Failed to probe rendered video: {exc}"],
        )

    # Validate video stream
    v_codec = "none"
    width, height = 0, 0
    if not probe.video_streams:
        errors.append("No video stream found in rendered output.")
    else:
        v_stream = probe.video_streams[0]
        v_codec = v_stream.codec_name
        width = v_stream.width
        height = v_stream.height
        if width != expected_width or height != expected_height:
            errors.append(
                f"Resolution mismatch: expected {expected_width}x{expected_height}, got {width}x{height}."
            )

    # Validate audio stream
    has_audio = len(probe.audio_streams) > 0
    a_codec = probe.audio_streams[0].codec_name if has_audio else "none"
    if not has_audio:
        errors.append("No audio stream found in rendered output.")

    # Validate duration
    dur_diff = abs(probe.duration_seconds - expected_duration)
    if dur_diff > duration_tolerance:
        errors.append(
            f"Duration mismatch: expected ~{expected_duration:.2f}s, got {probe.duration_seconds:.2f}s (diff={dur_diff:.2f}s)."
        )

    return RenderValidationResult(
        is_valid=(len(errors) == 0),
        output_path=p,
        file_size_bytes=file_size,
        duration_seconds=probe.duration_seconds,
        width=width,
        height=height,
        video_codec=v_codec,
        audio_codec=a_codec,
        has_audio=has_audio,
        validation_errors=errors,
    )


def render_candidate_clip(
    source_video_path: Path,
    candidate_start_seconds: float,
    candidate_end_seconds: float,
    output_mp4_path: Path,
    transcript_segments: Optional[List[TranscriptSegment]] = None,
    burn_subtitles: bool = True,
    framing_config: Optional[FramingConfig] = None,
    caption_config: Optional[CaptionConfig] = None,
    output_config: Optional[OutputConfig] = None,
    timeout_seconds: int = 300,
) -> RenderValidationResult:
    """Render a candidate clip into a vertical 9:16 MP4 using center crop and burned ASS subtitles.

    Workflow:
    1. Probe source video for resolution and audio stream presence.
    2. Build center-crop video filter.
    3. Generate clip-relative ASS subtitles if burn_subtitles=True.
    4. Execute FFmpeg with accurate seek (-ss before -i for fast seek, plus accurate trim).
    5. Validate rendered output against dimensions, duration, and audio presence.
    """
    installed, _ = check_ffmpeg_installed()
    if not installed:
        raise RenderError("FFmpeg executable not found in system PATH.")
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    source_path = Path(source_video_path).resolve()
    out_path = Path(output_mp4_path).resolve()

    if not source_path.exists():
        raise RenderError(f"Source video not found: {source_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = out_path.with_suffix(".rendering.mp4")

    # Clean any stale temp output
    if temp_output.exists():
        temp_output.unlink()

    duration = round(candidate_end_seconds - candidate_start_seconds, 3)
    if duration <= 0.0:
        raise RenderError(
            f"Invalid candidate duration: start={candidate_start_seconds}s, end={candidate_end_seconds}s"
        )

    source_probe = probe_media_file(source_path)
    if not source_probe.video_streams:
        raise RenderError(f"No video streams in source media: {source_path.name}")

    src_w = source_probe.video_streams[0].width
    src_h = source_probe.video_streams[0].height

    out_cfg = output_config or OutputConfig()
    crop_filter = build_center_crop_filter(
        source_width=src_w,
        source_height=src_h,
        target_width=out_cfg.width,
        target_height=out_cfg.height,
    )

    video_filters = [crop_filter]
    ass_subtitle_file: Optional[Path] = None

    # Step: Subtitles
    if burn_subtitles and transcript_segments:
        ass_subtitle_file = out_path.with_suffix(".ass")
        srt_subtitle_file = out_path.with_suffix(".srt")
        resolved_caption_cfg = resolve_caption_config(
            style_id=caption_config.preset_id if caption_config else None,
            canvas_width=out_cfg.width,
            overrides=caption_config,
        )
        write_subtitles_for_candidate(
            candidate_start_seconds=candidate_start_seconds,
            candidate_end_seconds=candidate_end_seconds,
            transcript_segments=transcript_segments,
            output_ass_path=ass_subtitle_file,
            output_srt_path=srt_subtitle_file,
            config=resolved_caption_cfg,
            canvas_width=out_cfg.width,
            canvas_height=out_cfg.height,
        )
        # Escape path for FFmpeg filter graph (handle Windows drive colon and backslashes)
        # Use FFmpeg subtitles filter which uses libass underneath and handles Windows paths robustly
        posix_ass = ass_subtitle_file.resolve().as_posix()
        if ":" in posix_ass:
            drive, rest = posix_ass.split(":", 1)
            escaped_ass = f"{drive}\\:{rest}"
        else:
            escaped_ass = posix_ass
        video_filters.append(f"subtitles='{escaped_ass}'")

    combined_filter = ",".join(video_filters)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", f"{candidate_start_seconds:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(source_path),
        "-vf", combined_filter,
        "-c:v", out_cfg.video_codec,
        "-preset", out_cfg.preset,
        "-crf", str(out_cfg.crf),
        "-pix_fmt", out_cfg.pixel_format,
        "-c:a", out_cfg.audio_codec,
        "-b:a", out_cfg.audio_bitrate,
        "-movflags", "+faststart",
        str(temp_output),
    ]

    logger.info(
        f"Rendering candidate clip [{candidate_start_seconds:.2f}s - {candidate_end_seconds:.2f}s] "
        f"(duration={duration:.2f}s, center_crop={out_cfg.width}x{out_cfg.height}, subtitles={burn_subtitles})..."
    )

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            if temp_output.exists():
                temp_output.unlink()
            logger.error(f"FFmpeg rendering failed: {proc.stderr}")
            raise RenderError(f"FFmpeg render process failed (code {proc.returncode}): {proc.stderr[:400]}")

        # Atomic rename to final output
        if out_path.exists():
            out_path.unlink()
        temp_output.replace(out_path)

    except subprocess.TimeoutExpired:
        if temp_output.exists():
            temp_output.unlink()
        raise RenderError(f"FFmpeg rendering timed out after {timeout_seconds}s")
    except Exception as exc:
        if temp_output.exists():
            temp_output.unlink()
        if isinstance(exc, RenderError):
            raise
        raise RenderError(f"Rendering execution failed: {exc}") from exc

    # Step: Validate rendered output
    validation = validate_rendered_output(
        output_path=out_path,
        expected_duration=duration,
        expected_width=out_cfg.width,
        expected_height=out_cfg.height,
    )

    if not validation.is_valid:
        logger.warning(f"Rendered clip validation warnings/errors: {validation.validation_errors}")

    return validation
