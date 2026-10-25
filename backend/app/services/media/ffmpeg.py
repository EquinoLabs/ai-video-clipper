"""Compatibility shim for common media FFmpeg utilities."""

from app.common.media.ffmpeg import (
    check_ffmpeg_installed,
    check_ffprobe_installed,
)

__all__ = [
    "check_ffmpeg_installed",
    "check_ffprobe_installed",
]
