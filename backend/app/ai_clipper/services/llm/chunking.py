"""Transcript chunking service with overlapping context windows."""

import logging
from typing import List
from pydantic import BaseModel, Field

from app.ai_clipper.domain.transcript.models import TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptChunk(BaseModel):
    """Normalized chunk of transcript segments for LLM context processing."""
    chunk_index: int = Field(..., ge=0, description="0-based index of this chunk")
    total_chunks: int = Field(..., ge=1, description="Total number of chunks in transcript")
    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of first segment in chunk")
    end_seconds: float = Field(..., ge=0.0, description="End timestamp of last segment in chunk")
    word_count: int = Field(..., ge=0, description="Total word count in chunk segments")
    segments: List[TranscriptSegment] = Field(..., description="Ordered list of segments in this chunk")
    formatted_text: str = Field(..., description="Timestamped plain text transcript for LLM prompting")


def format_segments_to_text(segments: List[TranscriptSegment], is_anchor_mode: bool = False) -> str:
    """Format segments into clean transcript lines for LLM prompting.
    
    If is_anchor_mode is True:
        Format: [SEG_{idx:02d}] Segment text (or speaker labeled)
        Uses chunk-local zero-indexed IDs to eliminate decimal math and token-copying bias.
    If is_anchor_mode is False (long-clip discovery):
        Format: [{start_seconds:.2f}s - {end_seconds:.2f}s] Segment text
    """
    lines = []
    for idx, s in enumerate(segments):
        if is_anchor_mode:
            speaker_prefix = f"({s.speaker_label}) " if s.speaker_label else ""
            lines.append(f"[SEG_{idx:02d}] {speaker_prefix}{s.text}")
        else:
            lines.append(f"[{s.start_seconds:.2f}s - {s.end_seconds:.2f}s] {s.text}")
    return "\n".join(lines)


def chunk_transcript(
    segments: List[TranscriptSegment],
    chunk_size_words: int = 2500,
    overlap_seconds: float = 45.0,
) -> List[TranscriptChunk]:
    """Split transcript segments into overlapping windows while preserving absolute timestamps.

    Args:
        segments: Complete ordered list of TranscriptSegment items.
        chunk_size_words: Target word budget per chunk (default: 2,500 words).
        overlap_seconds: Temporal overlap to retain from end of previous chunk (default: 45.0 seconds).

    Returns:
        List of TranscriptChunk objects covering the entire transcript.
    """
    if not segments:
        return []

    # If all segments easily fit within a single chunk, return 1 chunk
    total_words = sum(len(s.text.split()) for s in segments)
    if total_words <= chunk_size_words:
        first_seg = segments[0]
        last_seg = segments[-1]
        formatted = format_segments_to_text(segments)
        return [
            TranscriptChunk(
                chunk_index=0,
                total_chunks=1,
                start_seconds=first_seg.start_seconds,
                end_seconds=last_seg.end_seconds,
                word_count=total_words,
                segments=segments,
                formatted_text=formatted,
            )
        ]

    chunks_raw: List[List[TranscriptSegment]] = []
    current_chunk: List[TranscriptSegment] = []
    current_words = 0
    seg_idx = 0
    n = len(segments)

    while seg_idx < n:
        seg = segments[seg_idx]
        seg_word_count = len(seg.text.split())

        current_chunk.append(seg)
        current_words += seg_word_count
        seg_idx += 1

        # Check if current chunk has reached target word limit
        if current_words >= chunk_size_words and seg_idx < n:
            chunks_raw.append(current_chunk)
            # Find rollback point for overlapping context
            chunk_end_time = current_chunk[-1].end_seconds
            overlap_threshold = max(0.0, chunk_end_time - overlap_seconds)

            # Backtrack seg_idx to include segments starting after overlap_threshold
            backtrack_idx = seg_idx - 1
            while backtrack_idx > 0 and segments[backtrack_idx - 1].start_seconds >= overlap_threshold:
                backtrack_idx -= 1

            # Ensure we make forward progress: backtrack_idx must be < seg_idx
            # but if it backtracks all the way to start of current chunk, advance by at least 1 segment
            start_of_current_chunk_idx = seg_idx - len(current_chunk)
            if backtrack_idx <= start_of_current_chunk_idx:
                backtrack_idx = start_of_current_chunk_idx + 1

            seg_idx = backtrack_idx
            current_chunk = []
            current_words = 0

    if current_chunk:
        chunks_raw.append(current_chunk)

    total_chunks_count = len(chunks_raw)
    result_chunks: List[TranscriptChunk] = []

    for i, c_segs in enumerate(chunks_raw):
        c_words = sum(len(s.text.split()) for s in c_segs)
        result_chunks.append(
            TranscriptChunk(
                chunk_index=i,
                total_chunks=total_chunks_count,
                start_seconds=c_segs[0].start_seconds,
                end_seconds=c_segs[-1].end_seconds,
                word_count=c_words,
                segments=c_segs,
                formatted_text=format_segments_to_text(c_segs),
            )
        )

    logger.info(
        f"Partitioned transcript into {total_chunks_count} chunks "
        f"(target_words={chunk_size_words}, overlap={overlap_seconds}s)"
    )
    return result_chunks
