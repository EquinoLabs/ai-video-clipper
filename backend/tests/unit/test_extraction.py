"""Unit tests for audio extraction service."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.ai_clipper.services.media.extraction import (
    AudioExtractionError,
    extract_audio_to_wav,
)


def test_extract_audio_missing_input(tmp_path):
    missing_file = tmp_path / "nonexistent.mp4"
    out_wav = tmp_path / "out.wav"
    with pytest.raises(AudioExtractionError, match="Input file does not exist"):
        extract_audio_to_wav(missing_file, out_wav)


def test_extract_audio_command_construction(tmp_path):
    input_file = tmp_path / "source.mp4"
    input_file.write_text("dummy")
    out_wav = tmp_path / "extracted.wav"

    mock_run = MagicMock()
    mock_run.returncode = 0

    def fake_subprocess_run(cmd, **kwargs):
        # Create output file to simulate successful ffmpeg run
        out_wav.write_bytes(b"RIFF" + b"\x00" * 100)
        return mock_run

    with patch("shutil.which", return_value="C:/ffmpeg/bin/ffmpeg.exe"), \
         patch("subprocess.run", side_effect=fake_subprocess_run) as mocked_subproc:

        result = extract_audio_to_wav(
            input_video_path=input_file,
            output_wav_path=out_wav,
            stream_index=2,
            timeout_seconds=60.0,
        )

        assert result.output_path == out_wav
        assert result.sample_rate == 16000
        assert result.channels == 1
        assert result.codec == "pcm_s16le"
        assert result.size_bytes > 0

        # Verify command argument list
        called_cmd = mocked_subproc.call_args[0][0]
        assert called_cmd[0] == "C:/ffmpeg/bin/ffmpeg.exe"
        assert "-vn" in called_cmd
        assert "-map" in called_cmd
        map_idx = called_cmd.index("-map")
        assert called_cmd[map_idx + 1] == "0:2"
        assert "-acodec" in called_cmd
        acodec_idx = called_cmd.index("-acodec")
        assert called_cmd[acodec_idx + 1] == "pcm_s16le"
        assert "-ar" in called_cmd
        ar_idx = called_cmd.index("-ar")
        assert called_cmd[ar_idx + 1] == "16000"
        assert "-ac" in called_cmd
        ac_idx = called_cmd.index("-ac")
        assert called_cmd[ac_idx + 1] == "1"


def test_extract_audio_ffmpeg_failure_cleans_up(tmp_path):
    input_file = tmp_path / "source.mp4"
    input_file.write_text("dummy")
    out_wav = tmp_path / "extracted.wav"

    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "Invalid data found when processing input"

    with patch("shutil.which", return_value="C:/ffmpeg/bin/ffmpeg.exe"), \
         patch("subprocess.run", return_value=mock_run):

        # Pre-create corrupted partial file
        out_wav.write_bytes(b"partial")

        with pytest.raises(AudioExtractionError, match="FFmpeg audio extraction failed"):
            extract_audio_to_wav(input_file, out_wav)

        # Confirm partial file was deleted
        assert not out_wav.exists()
