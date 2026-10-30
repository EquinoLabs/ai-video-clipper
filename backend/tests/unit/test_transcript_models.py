"""Unit tests for transcript domain models and artifact serialization."""

import json
import pytest

from app.domain.transcript.models import (
    SourceMediaMetadata,
    TranscriptArtifact,
    TranscriptionRunMetadata,
    TranscriptSegment,
    WordTiming,
)


def test_word_timing_validation():
    # Valid
    w = WordTiming(word="hello", start_seconds=1.2, end_seconds=1.5, probability=0.98)
    assert w.word == "hello"
    assert w.end_seconds > w.start_seconds

    # Invalid: end < start
    with pytest.raises(ValueError, match="end_seconds .* < start_seconds"):
        WordTiming(word="bad", start_seconds=2.0, end_seconds=1.0)


def test_transcript_segment_validation_and_duration():
    seg = TranscriptSegment(
        id=0,
        start_seconds=10.0,
        end_seconds=14.5,
        duration_seconds=4.5,
        text="This is a test segment.",
        words=[
            WordTiming(word="This", start_seconds=10.0, end_seconds=10.3),
            WordTiming(word="is", start_seconds=10.3, end_seconds=10.5),
            WordTiming(word="a", start_seconds=10.5, end_seconds=10.7),
            WordTiming(word="test", start_seconds=10.7, end_seconds=11.1),
            WordTiming(word="segment", start_seconds=11.1, end_seconds=11.6),
        ],
    )
    assert seg.duration_seconds == 4.5
    assert len(seg.words) == 5


def test_transcript_artifact_serialization_roundtrip():
    artifact = TranscriptArtifact(
        schema_version="v1.0",
        source_media=SourceMediaMetadata(
            filename="interview.mp4",
            format_name="mov,mp4",
            duration_seconds=120.0,
            size_bytes=10485760,
            video_streams_count=1,
            audio_streams_count=1,
            selected_audio_stream_index=0,
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
        ),
        transcription=TranscriptionRunMetadata(
            provider="faster-whisper",
            model="base",
            language="en",
            language_probability=0.99,
            word_timestamps_enabled=True,
            duration_processed_seconds=120.0,
        ),
        word_timestamps_available=True,
        segment_count=1,
        total_words_count=2,
        warnings=[],
        segments=[
            TranscriptSegment(
                id=0,
                start_seconds=0.0,
                end_seconds=1.5,
                duration_seconds=1.5,
                text="Hello world.",
                words=[
                    WordTiming(word="Hello", start_seconds=0.0, end_seconds=0.6, probability=0.95),
                    WordTiming(word="world", start_seconds=0.6, end_seconds=1.2, probability=0.97),
                ],
            )
        ],
    )

    json_str = artifact.model_dump_json(indent=2)
    parsed = json.loads(json_str)

    assert parsed["schema_version"] == "v1.0"
    assert parsed["source_media"]["filename"] == "interview.mp4"
    assert parsed["transcription"]["provider"] == "faster-whisper"
    assert len(parsed["segments"]) == 1
    assert len(parsed["segments"][0]["words"]) == 2

    # Round trip deserialization
    reconstructed = TranscriptArtifact.model_validate_json(json_str)
    assert reconstructed.schema_version == artifact.schema_version
    assert reconstructed.segments[0].words[0].word == "Hello"
