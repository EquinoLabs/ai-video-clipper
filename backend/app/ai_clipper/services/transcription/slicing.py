"""Transcript slicing service for long clips, deriving long-local transcripts with preserved word timings."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from app.ai_clipper.domain.timeline.models import source_to_parent_local
from app.ai_clipper.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)

logger = logging.getLogger(__name__)


def slice_transcript_for_long_clip(
    source_artifact: TranscriptArtifact,
    clip_start_seconds: float,
    clip_end_seconds: float,
    clip_id: str,
) -> TranscriptArtifact:
    """Slice a source transcript artifact to create a self-contained long-clip transcript.

    Rules & Semantics:
    1. Select segments that have meaningful temporal overlap with [clip_start_seconds, clip_end_seconds].
    2. Convert segment and word timestamps to clip-local coordinates (local 0.0s = clip_start_seconds).
    3. Truncate segments that cross boundaries to fit cleanly inside the local interval [0.0, clip_duration].
    4. Filter word timings strictly inside the clip interval, shifting word.start_seconds and word.end_seconds
       by clip_start_seconds.
    5. Preserve genuine probabilities and words; never synthetically fabricate text or timings.
    6. Return a valid TranscriptArtifact with updated metadata and duration.
    """
    clip_duration = round(clip_end_seconds - clip_start_seconds, 3)
    if clip_duration <= 0.0:
        raise ValueError(
            f"Invalid clip boundaries: start={clip_start_seconds}s, end={clip_end_seconds}s (duration <= 0)"
        )

    local_segments: List[TranscriptSegment] = []
    seg_counter = 0

    for seg in source_artifact.segments:
        # Check temporal overlap
        overlap = min(seg.end_seconds, clip_end_seconds) - max(seg.start_seconds, clip_start_seconds)
        if overlap <= 0.001:
            continue

        # Segment bounds clamped to clip interval in source time
        clamped_src_start = max(seg.start_seconds, clip_start_seconds)
        clamped_src_end = min(seg.end_seconds, clip_end_seconds)

        # Convert to local time
        local_start = source_to_parent_local(clamped_src_start, clip_start_seconds, clip_end_seconds)
        local_end = source_to_parent_local(clamped_src_end, clip_start_seconds, clip_end_seconds)
        local_dur = round(local_end - local_start, 3)

        if local_dur <= 0.0:
            continue

        # Handle word timings
        local_words: Optional[List[WordTiming]] = None
        if seg.words:
            local_words = []
            for w in seg.words:
                # Include word if its midpoint or substantial span is inside the clip
                if w.end_seconds > clip_start_seconds and w.start_seconds < clip_end_seconds:
                    w_start_src = max(w.start_seconds, clip_start_seconds)
                    w_end_src = min(w.end_seconds, clip_end_seconds)
                    if w_end_src > w_start_src:
                        w_local_start = source_to_parent_local(w_start_src, clip_start_seconds, clip_end_seconds)
                        w_local_end = source_to_parent_local(w_end_src, clip_start_seconds, clip_end_seconds)
                        local_words.append(
                            WordTiming(
                                word=w.word,
                                start_seconds=w_local_start,
                                end_seconds=w_local_end,
                                probability=w.probability,
                            )
                        )
            if not local_words:
                local_words = None

        local_segments.append(
            TranscriptSegment(
                id=seg_counter,
                start_seconds=local_start,
                end_seconds=local_end,
                duration_seconds=local_dur,
                text=seg.text,
                words=local_words,
                speaker_label=seg.speaker_label,
            )
        )
        seg_counter += 1

    total_words = sum(len(s.words) for s in local_segments if s.words) if source_artifact.word_timestamps_available else None

    # Construct derived SourceMediaMetadata for the long clip
    clip_media_meta = SourceMediaMetadata(
        filename=f"{clip_id}.mp4",
        format_name=source_artifact.source_media.format_name,
        duration_seconds=clip_duration,
        size_bytes=0,  # Will be populated once rendered
        video_streams_count=source_artifact.source_media.video_streams_count,
        audio_streams_count=source_artifact.source_media.audio_streams_count,
        selected_audio_stream_index=source_artifact.source_media.selected_audio_stream_index,
        audio_codec=source_artifact.source_media.audio_codec,
        audio_sample_rate=source_artifact.source_media.audio_sample_rate,
        audio_channels=source_artifact.source_media.audio_channels,
    )

    clip_transcription_meta = TranscriptionRunMetadata(
        provider=source_artifact.transcription.provider,
        model=source_artifact.transcription.model,
        language=source_artifact.transcription.language,
        language_probability=source_artifact.transcription.language_probability,
        word_timestamps_enabled=source_artifact.transcription.word_timestamps_enabled,
        parameters=source_artifact.transcription.parameters,
        duration_processed_seconds=clip_duration,
    )

    return TranscriptArtifact(
        schema_version="v1.0",
        source_media=clip_media_meta,
        transcription=clip_transcription_meta,
        word_timestamps_available=source_artifact.word_timestamps_available and any(s.words for s in local_segments),
        segment_count=len(local_segments),
        total_words_count=total_words,
        warnings=[],
        segments=local_segments,
    )


def slice_transcript_for_short_clip(
    long_transcript: TranscriptArtifact,
    short_local_start_seconds: float,
    short_local_end_seconds: float,
    clip_id: str,
) -> TranscriptArtifact:
    """Slice a long-clip transcript artifact to create a self-contained short-clip transcript.

    Timings in long_transcript are relative to the parent long clip (0.0 to long_duration).
    short_local_start_seconds and short_local_end_seconds are offsets relative to the parent long clip.
    The resulting TranscriptArtifact has its own local coordinate system (0.0 to short_duration).
    """
    return slice_transcript_for_long_clip(
        source_artifact=long_transcript,
        clip_start_seconds=short_local_start_seconds,
        clip_end_seconds=short_local_end_seconds,
        clip_id=clip_id,
    )
