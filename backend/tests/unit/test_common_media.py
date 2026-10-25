"""Unit tests for shared common media infrastructure (ffmpeg and probing)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Common media imports
import app.common.media.ffmpeg as common_ffmpeg
import app.common.media.probing as common_probing
from app.common.media.ffmpeg import check_ffmpeg_installed, check_ffprobe_installed
from app.common.media.probing import (
    AudioStreamInfo,
    MediaProbeError,
    MediaProbeResult,
    MissingMediaEngineError,
    NoAudioStreamError,
    VideoStreamInfo,
    _parse_fps,
    probe_media_file,
)

# Legacy compatibility shim imports
import app.services.media.ffmpeg as shim_ffmpeg
import app.services.media.probing as shim_probing


def test_ffmpeg_probing_symbols_availability():
    """Verify all expected symbols are present in app.common.media."""
    assert callable(check_ffmpeg_installed)
    assert callable(check_ffprobe_installed)
    assert callable(probe_media_file)
    assert callable(_parse_fps)
    assert issubclass(VideoStreamInfo, object)
    assert issubclass(AudioStreamInfo, object)
    assert issubclass(MediaProbeResult, object)
    assert issubclass(MediaProbeError, Exception)
    assert issubclass(MissingMediaEngineError, MediaProbeError)
    assert issubclass(NoAudioStreamError, MediaProbeError)


def test_compatibility_shims_identity():
    """Verify compatibility shims re-export identical objects (class and function identity)."""
    assert shim_ffmpeg.check_ffmpeg_installed is common_ffmpeg.check_ffmpeg_installed
    assert shim_ffmpeg.check_ffprobe_installed is common_ffmpeg.check_ffprobe_installed

    assert shim_probing.probe_media_file is common_probing.probe_media_file
    assert shim_probing._parse_fps is common_probing._parse_fps
    assert shim_probing.VideoStreamInfo is common_probing.VideoStreamInfo
    assert shim_probing.AudioStreamInfo is common_probing.AudioStreamInfo
    assert shim_probing.MediaProbeResult is common_probing.MediaProbeResult
    assert shim_probing.MediaProbeError is common_probing.MediaProbeError
    assert shim_probing.MissingMediaEngineError is common_probing.MissingMediaEngineError
    assert shim_probing.NoAudioStreamError is common_probing.NoAudioStreamError


def test_ffmpeg_check_installed_mocked():
    """Verify check_ffmpeg_installed behaves correctly when binary is found or missing."""
    with patch("shutil.which", return_value=None):
        installed, version = check_ffmpeg_installed()
        assert installed is False
        assert version is None

    mock_run = MagicMock()
    mock_run.stdout = "ffmpeg version 7.1-full_build-www.gyan.dev Copyright (c) 2000-2024\nother info"
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("subprocess.run", return_value=mock_run):
            installed, version = check_ffmpeg_installed()
            assert installed is True
            assert "ffmpeg version 7.1" in version


def test_ffprobe_check_installed_mocked():
    """Verify check_ffprobe_installed behaves correctly when binary is found or missing."""
    with patch("shutil.which", return_value=None):
        installed, version = check_ffprobe_installed()
        assert installed is False
        assert version is None

    mock_run = MagicMock()
    mock_run.stdout = "ffprobe version 7.1-full_build Copyright\nmore"
    with patch("shutil.which", return_value="/usr/bin/ffprobe"):
        with patch("subprocess.run", return_value=mock_run):
            installed, version = check_ffprobe_installed()
            assert installed is True
            assert "ffprobe version 7.1" in version


def test_parse_fps_helper():
    """Verify _parse_fps helper function."""
    assert _parse_fps("30/1") == 30.0
    assert _parse_fps("24000/1001") == pytest.approx(23.976, 0.001)
    assert _parse_fps("invalid") is None
    assert _parse_fps(None) is None
    assert _parse_fps("0/0") is None


def test_probe_media_file_mocked_success(tmp_path: Path):
    """Verify probe_media_file returns validated MediaProbeResult from mocked ffprobe output."""
    dummy_video = tmp_path / "sample.mp4"
    dummy_video.write_bytes(b"mock video data")

    fake_ffprobe_json = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "12.500000",
            "size": "1048576",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "duration": "12.500000",
                "bit_rate": "800000",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "12.500000",
                "bit_rate": "192000",
            },
        ],
    }

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(fake_ffprobe_json)
    mock_result.stderr = ""

    with patch("shutil.which", return_value="/usr/bin/ffprobe"):
        with patch("subprocess.run", return_value=mock_result):
            res = probe_media_file(dummy_video)

    assert isinstance(res, MediaProbeResult)
    assert res.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert res.duration_seconds == 12.5
    assert len(res.video_streams) == 1
    assert res.video_streams[0].width == 1920
    assert res.video_streams[0].height == 1080
    assert res.video_streams[0].fps == 30.0
    assert len(res.audio_streams) == 1
    assert res.audio_streams[0].codec_name == "aac"
    assert res.selected_audio_stream_index == 0
    assert res.selected_audio_stream_id == 1
