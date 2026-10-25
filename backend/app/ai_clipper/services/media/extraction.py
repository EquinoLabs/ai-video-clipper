"""Audio extraction service using FFmpeg."""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AudioExtractionResult(BaseModel):
    output_path: Path
    sample_rate: int = 16000
    channels: int = 1
    codec: str = "pcm_s16le"
    size_bytes: int


class AudioExtractionError(Exception):
    """Raised when audio extraction fails or times out."""
    pass


def extract_audio_to_wav(
    input_video_path: Path,
    output_wav_path: Path,
    stream_index: Optional[int] = None,
    ffmpeg_bin: Optional[str] = None,
    timeout_seconds: float = 300.0,
) -> AudioExtractionResult:
    """Extract audio from input media file to standardized 16 kHz mono 16-bit PCM WAV.

    Audio Stream Selection Policy:
    - If stream_index is provided (e.g. from MediaProbeResult.selected_audio_stream_id),
      `-map 0:{stream_index}` is used to target that specific stream.
    - If stream_index is None, `-map 0:a:0` (first audio stream) is used as fallback.
    - Output is strictly 16 kHz, 1 channel (mono), signed 16-bit PCM WAV.

    Reliability:
    - On failure or timeout, any partially written output file is deleted to avoid corrupted state.
    """
    resolved_in = Path(input_video_path).resolve()
    resolved_out = Path(output_wav_path).resolve()

    if not resolved_in.exists() or not resolved_in.is_file():
        raise AudioExtractionError(f"Input file does not exist: {resolved_in}")

    resolved_out.parent.mkdir(parents=True, exist_ok=True)

    bin_path = ffmpeg_bin or shutil.which("ffmpeg")
    if not bin_path:
        raise AudioExtractionError("ffmpeg executable not found in system PATH.")

    # Construct safe command argument list
    map_arg = f"0:{stream_index}" if stream_index is not None else "0:a:0"
    cmd = [
        bin_path,
        "-y",                       # Overwrite output without prompting
        "-v", "error",              # Suppress chatty banner, emit errors
        "-i", str(resolved_in),     # Input media file
        "-vn",                      # Disable video recording
        "-map", map_arg,            # Explicit stream mapping
        "-acodec", "pcm_s16le",     # 16-bit PCM audio
        "-ar", "16000",             # 16 kHz sample rate
        "-ac", "1",                 # 1 channel (mono)
        str(resolved_out),
    ]

    logger.debug(f"Executing audio extraction: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if resolved_out.exists():
            resolved_out.unlink(missing_ok=True)
        raise AudioExtractionError(
            f"FFmpeg audio extraction timed out after {timeout_seconds}s for {resolved_in.name}"
        ) from exc
    except Exception as exc:
        if resolved_out.exists():
            resolved_out.unlink(missing_ok=True)
        raise AudioExtractionError(f"Failed to launch FFmpeg: {exc}") from exc

    if proc.returncode != 0:
        if resolved_out.exists():
            resolved_out.unlink(missing_ok=True)
        err_msg = proc.stderr.strip() or f"ffmpeg exited with status {proc.returncode}"
        raise AudioExtractionError(f"FFmpeg audio extraction failed: {err_msg}")

    if not resolved_out.exists():
        raise AudioExtractionError(f"Audio extraction completed but output file missing: {resolved_out}")

    size = resolved_out.stat().st_size
    if size == 0:
        resolved_out.unlink(missing_ok=True)
        raise AudioExtractionError(f"Extracted audio file is empty (0 bytes): {resolved_out}")

    return AudioExtractionResult(
        output_path=resolved_out,
        sample_rate=16000,
        channels=1,
        codec="pcm_s16le",
        size_bytes=size,
    )
