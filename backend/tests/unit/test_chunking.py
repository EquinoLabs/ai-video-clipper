"""Unit tests for transcript chunking with overlapping context."""

import pytest
from app.domain.transcript.models import TranscriptSegment
from app.services.llm.chunking import chunk_transcript, format_segments_to_text


def create_mock_segment(seg_id: int, start: float, duration: float, words_count: int) -> TranscriptSegment:
    words_text = " ".join([f"word{i}" for i in range(words_count)])
    return TranscriptSegment(
        id=seg_id,
        start_seconds=start,
        end_seconds=start + duration,
        duration_seconds=duration,
        text=words_text,
    )


def test_chunking_empty_segments():
    chunks = chunk_transcript([])
    assert chunks == []


def test_chunking_short_transcript_fits_in_single_chunk():
    segs = [
        create_mock_segment(0, 0.0, 5.0, 10),
        create_mock_segment(1, 5.0, 5.0, 15),
        create_mock_segment(2, 10.0, 5.0, 12),
    ]
    chunks = chunk_transcript(segs, chunk_size_words=100, overlap_seconds=10.0)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1
    assert chunks[0].start_seconds == 0.0
    assert chunks[0].end_seconds == 15.0
    assert chunks[0].word_count == 37
    assert len(chunks[0].segments) == 3


def test_chunking_long_transcript_preserves_overlap_and_absolute_timestamps():
    # 20 segments, each 10 seconds long with 20 words (total 400 words, 200 seconds)
    segs = [create_mock_segment(i, i * 10.0, 10.0, 20) for i in range(20)]

    # Target chunk size: 100 words (~5 segments), overlap: 30 seconds (~3 segments)
    chunks = chunk_transcript(segs, chunk_size_words=100, overlap_seconds=30.0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.total_chunks == len(chunks)
        assert chunk.start_seconds >= 0.0
        assert chunk.end_seconds > chunk.start_seconds
        # Segments in chunk must have monotonically non-decreasing start times
        for j in range(len(chunk.segments) - 1):
            assert chunk.segments[j].start_seconds <= chunk.segments[j + 1].start_seconds

    # Verify overlap between consecutive chunks
    for i in range(len(chunks) - 1):
        c1 = chunks[i]
        c2 = chunks[i + 1]
        # Chunk 2 must start before Chunk 1 ends
        assert c2.start_seconds < c1.end_seconds
        overlap = c1.end_seconds - c2.start_seconds
        assert overlap >= 20.0  # At least 2 segments overlapping (~20-30s)


def test_format_segments_to_text():
    segs = [
        TranscriptSegment(id=0, start_seconds=5.25, end_seconds=8.5, duration_seconds=3.25, text="Hello world"),
        TranscriptSegment(id=1, start_seconds=65.0, end_seconds=70.0, duration_seconds=5.0, text="One minute mark"),
    ]
    formatted = format_segments_to_text(segs)
    lines = formatted.split("\n")
    assert len(lines) == 2
    assert "[5.25s - 8.50s] Hello world" == lines[0]
    assert "[65.00s - 70.00s] One minute mark" == lines[1]


def test_chunking_medium_transcript_produces_multiple_windows_with_750_word_budget():
    """A ~2,000-word 10-minute transcript partitions into 3-4 chunks with ~750 words and 45s overlap."""
    # 135 segments of ~15 words each = 2,025 words across 600 seconds
    segs = [create_mock_segment(i, i * 4.44, 4.44, 15) for i in range(135)]
    chunks = chunk_transcript(segs, chunk_size_words=750, overlap_seconds=45.0)

    assert 3 <= len(chunks) <= 4
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i
        assert chunk.total_chunks == len(chunks)
        assert chunk.word_count > 0
        assert chunk.start_seconds >= 0.0
        assert chunk.end_seconds <= 605.0

    # Verify overlap exists between consecutive windows
    for i in range(len(chunks) - 1):
        assert chunks[i + 1].start_seconds < chunks[i].end_seconds
        overlap = chunks[i].end_seconds - chunks[i + 1].start_seconds
        assert overlap >= 40.0  # Around configured 45s overlap
