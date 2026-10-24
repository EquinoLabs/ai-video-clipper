"""FFmpeg and ffprobe discovery and media execution utilities."""

import asyncio
import logging
import shutil
import subprocess
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def check_ffmpeg_installed() -> Tuple[bool, Optional[str]]:
    """Check if ffmpeg executable is available in PATH and return its version line."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False, None

    try:
        result = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "Available"
        return True, first_line
    except Exception as exc:
        logger.warning(f"Error checking ffmpeg version: {exc}")
        return False, None


def check_ffprobe_installed() -> Tuple[bool, Optional[str]]:
    """Check if ffprobe executable is available in PATH and return its version line."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return False, None

    try:
        result = subprocess.run(
            [ffprobe_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "Available"
        return True, first_line
    except Exception as exc:
        logger.warning(f"Error checking ffprobe version: {exc}")
        return False, None
