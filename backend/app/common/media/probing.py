"""Media probing service using ffprobe."""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VideoStreamInfo(BaseModel):
    index: int
    codec_name: str
    width: int
    height: int
    fps: Optional[float] = None
    duration_seconds: Optional[float] = None
    bit_rate: Optional[int] = None


class AudioStreamInfo(BaseModel):
    index: int
    stream_index: int
    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: Optional[str] = None
    duration_seconds: Optional[float] = None
    bit_rate: Optional[int] = None


class MediaProbeResult(BaseModel):
    format_name: str
    duration_seconds: float
    size_bytes: int
    video_streams: List[VideoStreamInfo] = Field(default_factory=list)
    audio_streams: List[AudioStreamInfo] = Field(default_factory=list)
    selected_audio_stream_index: int = Field(
        ...,
        description="Index of selected audio stream among audio streams (0-based)",
    )
    selected_audio_stream_id: int = Field(
        ...,
        description="Stream index in container (used for ffprobe/ffmpeg -map)",
    )


class MediaProbeError(Exception):
    """Raised when media probing fails due to missing file, unsupported format, or ffprobe error."""
    pass


class MissingMediaEngineError(MediaProbeError):
    """Raised when ffprobe executable is not found."""
    pass


class NoAudioStreamError(MediaProbeError):
    """Raised when the input media has no decodable audio streams."""
    pass


def _parse_fps(fps_str: Optional[str]) -> Optional[float]:
    if not fps_str or fps_str == "0/0":
        return None
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            denominator = float(den)
            return float(num) / denominator if denominator != 0 else None
        return float(fps_str)
    except Exception:
        return None


def probe_media_file(
    file_path: Path,
    ffprobe_bin: Optional[str] = None,
    timeout_seconds: float = 20.0,
) -> MediaProbeResult:
    """Probe media file with ffprobe and extract validated stream metadata.

    Audio stream selection policy:
    1. Collect all streams where codec_type == 'audio'.
    2. If no audio streams exist, raise NoAudioStreamError.
    3. If multiple audio streams exist, default to the first valid audio stream (index 0).
       (A future configuration can support explicit language or channel selection).
    """
    resolved_path = Path(file_path).resolve()
    if not resolved_path.exists():
        raise MediaProbeError(f"File not found: {resolved_path}")
    if not resolved_path.is_file():
        raise MediaProbeError(f"Path is not a regular file: {resolved_path}")
    if resolved_path.stat().st_size == 0:
        raise MediaProbeError(f"File is empty (0 bytes): {resolved_path}")

    bin_path = ffprobe_bin or shutil.which("ffprobe")
    if not bin_path:
        raise MissingMediaEngineError("ffprobe executable not found in system PATH.")

    cmd = [
        bin_path,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(resolved_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProbeError(f"ffprobe timed out after {timeout_seconds} seconds") from exc
    except Exception as exc:
        raise MediaProbeError(f"Failed to execute ffprobe: {exc}") from exc

    if result.returncode != 0:
        err_msg = result.stderr.strip() or f"ffprobe exited with code {result.returncode}"
        raise MediaProbeError(f"Invalid or corrupted media file: {err_msg}")

    try:
        data: Dict[str, Any] = json.loads(result.stdout)
    except Exception as exc:
        raise MediaProbeError(f"Malformed ffprobe JSON output: {exc}") from exc

    format_data = data.get("format", {})
    streams_data = data.get("streams", [])

    duration_str = format_data.get("duration")
    size_str = format_data.get("size")

    try:
        duration_seconds = float(duration_str) if duration_str else 0.0
    except ValueError:
        duration_seconds = 0.0

    try:
        size_bytes = int(size_str) if size_str else resolved_path.stat().st_size
    except ValueError:
        size_bytes = resolved_path.stat().st_size

    video_streams: List[VideoStreamInfo] = []
    audio_streams: List[AudioStreamInfo] = []

    audio_counter = 0
    for stream in streams_data:
        codec_type = stream.get("codec_type")
        stream_idx = stream.get("index", 0)

        if codec_type == "video":
            fps = _parse_fps(stream.get("r_frame_rate")) or _parse_fps(stream.get("avg_frame_rate"))
            try:
                v_dur = float(stream.get("duration")) if stream.get("duration") else None
            except ValueError:
                v_dur = None
            try:
                v_bitrate = int(stream.get("bit_rate")) if stream.get("bit_rate") else None
            except ValueError:
                v_bitrate = None

            video_streams.append(
                VideoStreamInfo(
                    index=stream_idx,
                    codec_name=stream.get("codec_name", "unknown"),
                    width=int(stream.get("width", 0)),
                    height=int(stream.get("height", 0)),
                    fps=fps,
                    duration_seconds=v_dur,
                    bit_rate=v_bitrate,
                )
            )

        elif codec_type == "audio":
            try:
                sample_rate = int(stream.get("sample_rate", 0))
            except ValueError:
                sample_rate = 0

            try:
                channels = int(stream.get("channels", 0))
            except ValueError:
                channels = 0

            try:
                a_dur = float(stream.get("duration")) if stream.get("duration") else None
            except ValueError:
                a_dur = None

            try:
                a_bitrate = int(stream.get("bit_rate")) if stream.get("bit_rate") else None
            except ValueError:
                a_bitrate = None

            audio_streams.append(
                AudioStreamInfo(
                    index=audio_counter,
                    stream_index=stream_idx,
                    codec_name=stream.get("codec_name", "unknown"),
                    sample_rate=sample_rate,
                    channels=channels,
                    channel_layout=stream.get("channel_layout"),
                    duration_seconds=a_dur,
                    bit_rate=a_bitrate,
                )
            )
            audio_counter += 1

    if not audio_streams:
        raise NoAudioStreamError(
            f"No audio streams detected in media file: {resolved_path.name}. "
            "AI Video Clipper requires speech audio."
        )

    # If format duration is 0, attempt fallback from streams
    if duration_seconds <= 0.0:
        stream_durations = [
            s.duration_seconds
            for s in (*video_streams, *audio_streams)
            if s.duration_seconds is not None and s.duration_seconds > 0
        ]
        duration_seconds = max(stream_durations) if stream_durations else 0.0

    selected_audio = audio_streams[0]

    return MediaProbeResult(
        format_name=format_data.get("format_name", "unknown"),
        duration_seconds=duration_seconds,
        size_bytes=size_bytes,
        video_streams=video_streams,
        audio_streams=audio_streams,
        selected_audio_stream_index=selected_audio.index,
        selected_audio_stream_id=selected_audio.stream_index,
    )
