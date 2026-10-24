"""Unit tests for media probing service."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.services.media.probing import (
    MediaProbeError,
    MissingMediaEngineError,
    NoAudioStreamError,
    _parse_fps,
    probe_media_file,
)


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.97, 0.01)
    assert _parse_fps("60/1") == 60.0
    assert _parse_fps("0/0") is None
    assert _parse_fps(None) is None


def test_probe_media_file_not_found(tmp_path):
    non_existent = tmp_path / "does_not_exist.mp4"
    with pytest.raises(MediaProbeError, match="File not found"):
        probe_media_file(non_existent)


def test_probe_media_file_empty(tmp_path):
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_text("")
    with pytest.raises(MediaProbeError, match="File is empty"):
        probe_media_file(empty_file)


def test_probe_media_missing_engine(tmp_path):
    dummy_file = tmp_path / "test.mp4"
    dummy_file.write_text("dummy video content")
    with patch("shutil.which", return_value=None):
        with pytest.raises(MissingMediaEngineError, match="ffprobe executable not found"):
            probe_media_file(dummy_file)


def test_probe_media_success(tmp_path):
    dummy_file = tmp_path / "video.mp4"
    dummy_file.write_text("data")

    fake_ffprobe_output = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "120.5",
            "size": "5000000",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "duration": "120.5",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "120.5",
            },
        ],
    }

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps(fake_ffprobe_output)
    mock_run.stderr = ""

    with patch("shutil.which", return_value="C:/ffmpeg/bin/ffprobe.exe"), \
         patch("subprocess.run", return_value=mock_run):
        result = probe_media_file(dummy_file)

        assert result.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
        assert result.duration_seconds == 120.5
        assert len(result.video_streams) == 1
        assert result.video_streams[0].width == 1920
        assert result.video_streams[0].fps == 30.0
        assert len(result.audio_streams) == 1
        assert result.audio_streams[0].codec_name == "aac"
        assert result.selected_audio_stream_index == 0
        assert result.selected_audio_stream_id == 1


def test_probe_media_no_audio_streams(tmp_path):
    dummy_file = tmp_path / "video_no_audio.mp4"
    dummy_file.write_text("data")

    fake_ffprobe_output = {
        "format": {"format_name": "mp4", "duration": "10.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}
        ],
    }

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps(fake_ffprobe_output)

    with patch("shutil.which", return_value="C:/ffmpeg/bin/ffprobe.exe"), \
         patch("subprocess.run", return_value=mock_run):
        with pytest.raises(NoAudioStreamError, match="No audio streams detected"):
            probe_media_file(dummy_file)
