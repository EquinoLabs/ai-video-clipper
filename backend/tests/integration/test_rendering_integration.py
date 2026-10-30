"""Integration tests for Phase 3: video trimming, 9:16 center-crop rendering, and validation."""

import subprocess
from pathlib import Path
import pytest

from app.domain.rendering.models import CaptionConfig, OutputConfig
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.media.ffmpeg import check_ffmpeg_installed, check_ffprobe_installed
from app.services.media.rendering import (
    build_center_crop_filter,
    render_candidate_clip,
    validate_rendered_output,
)

ffmpeg_available, _ = check_ffmpeg_installed()
ffprobe_available, _ = check_ffprobe_installed()
skip_if_no_ffmpeg = pytest.mark.skipif(
    not (ffmpeg_available and ffprobe_available),
    reason="FFmpeg/FFprobe binaries not available in PATH",
)


@pytest.fixture
def synthetic_landscape_video(tmp_path: Path) -> Path:
    """Generate a valid 5-second 16:9 640x360 test MP4 file with sine wave audio."""
    output_mp4 = tmp_path / "test_16x9_source.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(output_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Failed to generate test video: {res.stderr}"
    assert output_mp4.exists() and output_mp4.stat().st_size > 0
    return output_mp4


def test_build_center_crop_filter():
    # 1920x1080 (16:9 landscape) -> target 1080x1920 (9:16)
    # crop_h = 1080, crop_w = 1080 * 9 / 16 = 607.5 -> 606 (even)
    filter_str = build_center_crop_filter(1920, 1080, 1080, 1920)
    assert "crop=606:1080" in filter_str
    assert "scale=1080:1920" in filter_str


@skip_if_no_ffmpeg
def test_render_candidate_clip_end_to_end(synthetic_landscape_video: Path, tmp_path: Path):
    """Verify trimming, 9:16 vertical center crop, and validation on real MP4."""
    out_mp4 = tmp_path / "rendered_vertical_clip.mp4"

    mock_segments = [
        TranscriptSegment(
            id=0,
            start_seconds=1.0,
            end_seconds=4.0,
            duration_seconds=3.0,
            text="Testing vertical rendering and captions.",
            words=[
                WordTiming(word="Testing", start_seconds=1.0, end_seconds=1.8),
                WordTiming(word="vertical", start_seconds=1.8, end_seconds=2.6),
                WordTiming(word="rendering", start_seconds=2.6, end_seconds=3.4),
                WordTiming(word="captions", start_seconds=3.4, end_seconds=4.0),
            ],
        )
    ]

    out_cfg = OutputConfig(width=360, height=640)  # Lower res for fast unit test execution

    val_res = render_candidate_clip(
        source_video_path=synthetic_landscape_video,
        candidate_start_seconds=1.0,
        candidate_end_seconds=4.0,  # 3.0 seconds duration
        output_mp4_path=out_mp4,
        transcript_segments=mock_segments,
        burn_subtitles=True,
        output_config=out_cfg,
    )

    assert val_res.is_valid is True
    assert val_res.output_path.exists()
    assert val_res.file_size_bytes > 0
    assert val_res.width == 360
    assert val_res.height == 640
    assert val_res.duration_seconds == pytest.approx(3.0, 0.4)
    assert val_res.has_audio is True
    assert val_res.video_codec == "h264"
    assert val_res.audio_codec == "aac"
    assert len(val_res.validation_errors) == 0
