"""Integration test verifying real faster-whisper model loading and speech transcription."""

from pathlib import Path
import pytest

from app.ai_clipper.services.transcription.faster_whisper_adapter import FasterWhisperAdapter


def test_real_faster_whisper_transcription():
    sample_wav = Path(__file__).parent.parent / "fixtures" / "sample_speech.wav"
    assert sample_wav.exists(), "Sample speech WAV fixture missing"

    adapter = FasterWhisperAdapter(model_size_or_path="tiny", device="cpu", compute_type="int8")
    result = adapter.transcribe(sample_wav, word_timestamps=True)

    assert result.provider == "faster-whisper"
    assert result.model == "tiny"
    assert result.language == "en"
    assert len(result.segments) >= 1

    first_seg = result.segments[0]
    assert "video clipper" in first_seg.text.lower() or "clipper" in first_seg.text.lower()
    assert first_seg.start_seconds >= 0.0
    assert first_seg.end_seconds > first_seg.start_seconds

    # Verify word timestamps
    assert result.word_timestamps_available is True
    assert first_seg.words is not None
    assert len(first_seg.words) > 0
    assert first_seg.words[0].end_seconds >= first_seg.words[0].start_seconds
