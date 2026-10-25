"""Fake TTS provider for offline development and testing.

Produces schema-valid, playable silence WAV files with exact requested durations,
allowing offline development of scene timing and ffmpeg concatenation without
requiring external TTS models or network APIs.
"""

import wave
from pathlib import Path
from typing import Union


class FakeTTSProvider:
    """Offline development TTS provider generating silence WAV files."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1, sampwidth: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.sampwidth = sampwidth  # 2 bytes = 16-bit PCM

    def synthesize_silence(
        self,
        duration_seconds: float,
        output_path: Union[str, Path],
    ) -> Path:
        """Generate a valid 16-bit PCM WAV file containing silence.

        Args:
            duration_seconds: Duration of silence in seconds.
            output_path: Path where the WAV file will be written.

        Returns:
            Path to the written WAV file.
        """
        if duration_seconds < 0:
            raise ValueError(f"duration_seconds must be non-negative, received {duration_seconds}")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        num_frames = int(round(duration_seconds * self.sample_rate))
        silence_bytes = b"\x00" * (num_frames * self.channels * self.sampwidth)

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sampwidth)
            wf.setframerate(self.sample_rate)
            wf.writeframes(silence_bytes)

        return out_path
