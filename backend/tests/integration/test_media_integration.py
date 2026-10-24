"""Integration tests using real FFmpeg and ffprobe binaries."""

import shutil
import subprocess
from pathlib import Path
import pytest

from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.media.extraction import extract_audio_to_wav
from app.services.media.ffmpeg import check_ffmpeg_installed, check_ffprobe_installed
from app.services.media.probing import probe_media_file
from app.services.pipeline.local_pipeline import run_local_pipeline
from app.services.transcription.base import TranscriptionProvider, TranscriptionResult

ffmpeg_available, _ = check_ffmpeg_installed()
ffprobe_available, _ = check_ffprobe_installed()
skip_if_no_ffmpeg = pytest.mark.skipif(
    not (ffmpeg_available and ffprobe_available),
    reason="FFmpeg/FFprobe binaries not available in PATH",
)


@pytest.fixture
def synthetic_test_video(tmp_path: Path) -> Path:
    """Generate a valid 2-second test MP4 file with video and sine wave audio using FFmpeg."""
    output_mp4 = tmp_path / "test_synthetic.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(output_mp4),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"Failed to generate test video: {res.stderr}"
    assert output_mp4.exists() and output_mp4.stat().st_size > 0
    return output_mp4


class MockTranscriptionProvider(TranscriptionProvider):
    """Deterministic mock provider for testing full pipeline without loading heavy weights."""

    def transcribe(
        self,
        audio_file_path: Path,
        word_timestamps: bool = True,
        language: str = None,
        max_duration_seconds: float = None,
    ) -> TranscriptionResult:
        assert audio_file_path.exists()
        return TranscriptionResult(
            segments=[
                TranscriptSegment(
                    id=0,
                    start_seconds=0.2,
                    end_seconds=1.8,
                    duration_seconds=1.6,
                    text="Synthetic speech test segment.",
                    words=[
                        WordTiming(word="Synthetic", start_seconds=0.2, end_seconds=0.6, probability=0.98),
                        WordTiming(word="speech", start_seconds=0.6, end_seconds=1.0, probability=0.99),
                        WordTiming(word="test", start_seconds=1.0, end_seconds=1.4, probability=0.97),
                        WordTiming(word="segment.", start_seconds=1.4, end_seconds=1.8, probability=0.95),
                    ] if word_timestamps else None,
                )
            ],
            language="en",
            language_probability=0.99,
            duration_seconds=2.0,
            word_timestamps_available=word_timestamps,
            provider="mock-whisper",
            model="mock",
        )


@skip_if_no_ffmpeg
def test_real_ffmpeg_probing_and_extraction(synthetic_test_video: Path, tmp_path: Path):
    # 1. Real probe
    probe_res = probe_media_file(synthetic_test_video)
    assert probe_res.duration_seconds == pytest.approx(2.0, 0.2)
    assert len(probe_res.video_streams) == 1
    assert probe_res.video_streams[0].width == 320
    assert probe_res.video_streams[0].height == 240
    assert len(probe_res.audio_streams) == 1
    assert probe_res.audio_streams[0].codec_name == "aac"

    # 2. Real audio extraction to 16kHz mono WAV
    out_wav = tmp_path / "extracted_real.wav"
    ext_res = extract_audio_to_wav(
        input_video_path=synthetic_test_video,
        output_wav_path=out_wav,
        stream_index=probe_res.selected_audio_stream_id,
    )

    assert ext_res.output_path.exists()
    assert ext_res.sample_rate == 16000
    assert ext_res.channels == 1
    assert ext_res.codec == "pcm_s16le"
    assert ext_res.size_bytes > 0

    # 3. Probe the extracted WAV to verify format
    wav_probe = probe_media_file(out_wav)
    assert len(wav_probe.audio_streams) == 1
    assert wav_probe.audio_streams[0].sample_rate == 16000
    assert wav_probe.audio_streams[0].channels == 1
    assert wav_probe.audio_streams[0].codec_name == "pcm_s16le"


@skip_if_no_ffmpeg
def test_full_local_pipeline_execution(synthetic_test_video: Path, tmp_path: Path):
    out_dir = tmp_path / "pipeline_run"
    mock_provider = MockTranscriptionProvider()

    result = run_local_pipeline(
        source_file_path=synthetic_test_video,
        output_dir=out_dir,
        transcription_provider=mock_provider,
        word_timestamps=True,
        keep_audio=True,
    )

    assert result.transcript_artifact_path.exists()
    assert result.extracted_audio_path.exists()
    assert result.artifact.schema_version == "v1.0"
    assert result.artifact.segment_count == 1
    assert result.artifact.word_timestamps_available is True
    assert result.artifact.source_media.filename == synthetic_test_video.name
    assert result.artifact.source_media.duration_seconds == pytest.approx(2.0, 0.2)
