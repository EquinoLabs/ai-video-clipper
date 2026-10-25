"""Unit tests verifying transcript and word timestamp boundary enforcement and clamping."""

import math
from pathlib import Path
from typing import List, Optional
import pytest

from app.ai_clipper.domain.transcript.models import TranscriptSegment, WordTiming
from app.ai_clipper.services.transcription.base import TranscriptionProviderError
from app.ai_clipper.services.transcription.faster_whisper_adapter import FasterWhisperAdapter


class MockWhisperRawWord:
    def __init__(self, word: str, start: float, end: float, probability: Optional[float] = 0.95):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class MockWhisperRawSegment:
    def __init__(
        self,
        text: str,
        start: float,
        end: float,
        words: Optional[List[MockWhisperRawWord]] = None,
    ):
        self.text = text
        self.start = start
        self.end = end
        self.words = words


class MockWhisperModelWrapper:
    """Mock model that returns predetermined segments without executing CTranslate2."""

    def __init__(self, raw_segments: List[MockWhisperRawSegment], language: str = "en", duration: float = 30.0):
        self.raw_segments = raw_segments
        self.language = language
        self.duration = duration

    def transcribe(self, audio_path: str, **kwargs):
        class MockInfo:
            language = self.language
            language_probability = 0.99
            duration = self.duration

        return iter(self.raw_segments), MockInfo()


@pytest.fixture
def dummy_audio_file(tmp_path: Path) -> Path:
    audio_path = tmp_path / "dummy.wav"
    audio_path.write_bytes(b"RIFFdummydataWAVEfmt ")
    return audio_path


def test_segment_ending_beyond_source_duration(dummy_audio_file: Path):
    """Requirement 3.1: Segment ending beyond source duration must be clamped to max_duration."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Hello world beyond limit",
            start=8.0,
            end=14.5,  # Exceeds max_duration=10.0
            words=[
                MockWhisperRawWord("Hello", 8.0, 9.0),
                MockWhisperRawWord("world", 9.0, 11.0),   # Crosses boundary
                MockWhisperRawWord("beyond", 11.0, 13.0), # Outside boundary
                MockWhisperRawWord("limit", 13.0, 14.5),  # Outside boundary
            ],
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True, max_duration_seconds=10.0)

    assert len(res.segments) == 1
    seg = res.segments[0]
    assert seg.start_seconds == 8.0
    assert seg.end_seconds == 10.0
    assert seg.duration_seconds == 2.0

    # Verify words within segment
    assert seg.words is not None
    assert len(seg.words) >= 1
    for w in seg.words:
        assert 8.0 <= w.start_seconds <= w.end_seconds <= 10.0
        assert seg.start_seconds <= w.start_seconds <= w.end_seconds <= seg.end_seconds


def test_segment_starting_beyond_source_duration(dummy_audio_file: Path):
    """Requirement 3.2: Segment starting beyond source duration must be dropped."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Valid first segment",
            start=2.0,
            end=5.0,
            words=[
                MockWhisperRawWord("Valid", 2.0, 3.0),
                MockWhisperRawWord("first", 3.0, 4.0),
                MockWhisperRawWord("segment", 4.0, 5.0),
            ],
        ),
        MockWhisperRawSegment(
            text="Trailing segment after video end",
            start=10.2,  # > max_duration=10.0
            end=12.0,
            words=[MockWhisperRawWord("Trailing", 10.2, 12.0)],
        ),
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True, max_duration_seconds=10.0)

    assert len(res.segments) == 1
    assert res.segments[0].text == "Valid first segment"
    assert res.segments[0].end_seconds <= 10.0


def test_word_ending_beyond_parent_segment(dummy_audio_file: Path):
    """Requirement 3.3: Word ending beyond parent segment must be clamped to segment.end_seconds."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Testing word end overrun",
            start=1.0,
            end=4.0,
            words=[
                MockWhisperRawWord("Testing", 1.0, 2.0),
                MockWhisperRawWord("word", 2.0, 3.0),
                MockWhisperRawWord("end", 3.0, 3.5),
                MockWhisperRawWord("overrun", 3.5, 4.8),  # 4.8 > seg_end=4.0
            ],
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True)

    assert len(res.segments) == 1
    seg = res.segments[0]
    assert seg.end_seconds == 4.0
    last_word = seg.words[-1]
    assert last_word.word == "overrun"
    assert last_word.start_seconds == 3.5
    assert last_word.end_seconds == 4.0
    assert last_word.end_seconds <= seg.end_seconds


def test_word_starting_beyond_parent_segment(dummy_audio_file: Path):
    """Requirement 3.4: Word starting beyond parent segment must not violate boundaries or invent times."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Valid words and late word",
            start=2.0,
            end=5.0,
            words=[
                MockWhisperRawWord("Valid", 2.0, 3.0),
                MockWhisperRawWord("words", 3.0, 4.0),
                MockWhisperRawWord("and", 4.0, 4.8),
                MockWhisperRawWord("late", 5.2, 5.8),  # starts beyond seg_end=5.0
            ],
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True)

    seg = res.segments[0]
    for w in seg.words:
        assert seg.start_seconds <= w.start_seconds <= w.end_seconds <= seg.end_seconds


def test_word_with_inverted_or_malformed_raw_interval(dummy_audio_file: Path):
    """Requirement 3.5: Word with inverted or malformed raw interval must never produce end < start."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Good and inverted words",
            start=1.0,
            end=5.0,
            words=[
                MockWhisperRawWord("Good", 1.0, 2.0),
                MockWhisperRawWord("inverted", 3.5, 2.8),  # Inverted raw timing: start 3.5 > end 2.8
                MockWhisperRawWord("words", 3.6, 4.5),
            ],
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True)

    seg = res.segments[0]
    for w in seg.words:
        assert w.start_seconds <= w.end_seconds
        assert seg.start_seconds <= w.start_seconds <= w.end_seconds <= seg.end_seconds


def test_overlapping_valid_word_intervals_preserved(dummy_audio_file: Path):
    """Verify that naturally overlapping words from Whisper are preserved without truncation or shifting."""
    raw_segments = [
        MockWhisperRawSegment(
            text="They are speaking fast",
            start=1.0,
            end=4.0,
            words=[
                MockWhisperRawWord("They", 1.0, 1.8),
                MockWhisperRawWord("are", 1.6, 2.3),      # Overlaps "They" (1.6 < 1.8)
                MockWhisperRawWord("speaking", 2.1, 3.2), # Overlaps "are" (2.1 < 2.3)
                MockWhisperRawWord("fast", 3.0, 3.9),     # Overlaps "speaking" (3.0 < 3.2)
            ],
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True)

    seg = res.segments[0]
    assert len(seg.words) == 4
    # Check that exact model-emitted timestamps are preserved unmodified
    assert (seg.words[0].word, seg.words[0].start_seconds, seg.words[0].end_seconds) == ("They", 1.0, 1.8)
    assert (seg.words[1].word, seg.words[1].start_seconds, seg.words[1].end_seconds) == ("are", 1.6, 2.3)
    assert (seg.words[2].word, seg.words[2].start_seconds, seg.words[2].end_seconds) == ("speaking", 2.1, 3.2)
    assert (seg.words[3].word, seg.words[3].start_seconds, seg.words[3].end_seconds) == ("fast", 3.0, 3.9)

    for w in seg.words:
        assert seg.start_seconds <= w.start_seconds <= w.end_seconds <= seg.end_seconds


def test_transcription_without_optional_duration_limit(dummy_audio_file: Path):
    """Requirement 3.6: Transcription without max_duration_seconds retains full unclipped range."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Segment one in long video",
            start=5.0,
            end=15.0,
            words=[MockWhisperRawWord("Segment", 5.0, 7.0), MockWhisperRawWord("one", 7.0, 15.0)],
        ),
        MockWhisperRawSegment(
            text="Segment two at one hour mark",
            start=3600.0,
            end=3610.0,
            words=[MockWhisperRawWord("Segment", 3600.0, 3605.0), MockWhisperRawWord("two", 3605.0, 3610.0)],
        ),
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True, max_duration_seconds=None)

    assert len(res.segments) == 2
    assert res.segments[0].start_seconds == 5.0
    assert res.segments[0].end_seconds == 15.0
    assert res.segments[1].start_seconds == 3600.0
    assert res.segments[1].end_seconds == 3610.0


def test_missing_word_timestamps_and_no_fabricated_timings(dummy_audio_file: Path):
    """Requirement 3.7: When word timestamps are disabled or absent, words list is None without synthetic timings."""
    raw_segments = [
        MockWhisperRawSegment(
            text="Segment with no word timings available",
            start=2.0,
            end=6.0,
            words=None,  # No word-level timings
        )
    ]
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    adapter._model = MockWhisperModelWrapper(raw_segments)

    res = adapter.transcribe(dummy_audio_file, word_timestamps=True)

    assert len(res.segments) == 1
    seg = res.segments[0]
    assert seg.start_seconds == 2.0
    assert seg.end_seconds == 6.0
    assert seg.words is None
    assert res.word_timestamps_available is False
    assert any("Word-level timestamps were requested but not returned" in w for w in res.warnings)


@pytest.mark.parametrize("invalid_duration", [-5.0, 0.0, -0.001, float("nan"), float("inf"), float("-inf"), "invalid"])
def test_invalid_duration_limits_rejected(dummy_audio_file: Path, invalid_duration):
    """Requirement 3.8: Negative, zero, NaN, infinite, or non-numeric duration limits raise ValueError."""
    adapter = FasterWhisperAdapter(model_size_or_path="mock")
    with pytest.raises(ValueError, match="max_duration_seconds must be a positive, finite number"):
        adapter.transcribe(dummy_audio_file, max_duration_seconds=invalid_duration)
