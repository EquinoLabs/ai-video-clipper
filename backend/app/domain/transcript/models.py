"""Transcript domain models and artifact schema."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class WordTiming(BaseModel):
    """Word-level timing information strictly when emitted by model.
    Never synthetically interpolated.
    """
    word: str = Field(..., description="The word text")
    start_seconds: float = Field(..., ge=0.0, description="Start time in source video timeline (seconds)")
    end_seconds: float = Field(..., ge=0.0, description="End time in source video timeline (seconds)")
    probability: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence probability (0.0 to 1.0)")

    @model_validator(mode="after")
    def validate_bounds(self) -> "WordTiming":
        if self.end_seconds < self.start_seconds:
            raise ValueError(f"Word end_seconds ({self.end_seconds}) < start_seconds ({self.start_seconds})")
        return self


class TranscriptSegment(BaseModel):
    """Normalized transcript segment with absolute source-video timestamps."""
    id: int = Field(..., ge=0, description="Sequential segment index")
    start_seconds: float = Field(..., ge=0.0, description="Absolute start time (seconds)")
    end_seconds: float = Field(..., ge=0.0, description="Absolute end time (seconds)")
    duration_seconds: float = Field(..., ge=0.0, description="Duration derived as end - start")
    text: str = Field(..., min_length=1, description="Transcript text")
    words: Optional[List[WordTiming]] = Field(
        None,
        description="Genuine word-level timings if available; null if unavailable",
    )
    speaker_label: Optional[str] = Field(
        None,
        description="Speaker identity if provided by diarization; null for local Whisper baseline",
    )

    @model_validator(mode="after")
    def validate_segment(self) -> "TranscriptSegment":
        if self.end_seconds < self.start_seconds:
            raise ValueError(f"Segment end_seconds ({self.end_seconds}) < start_seconds ({self.start_seconds})")
        # Ensure duration_seconds matches end - start
        computed_duration = round(self.end_seconds - self.start_seconds, 3)
        if abs(self.duration_seconds - computed_duration) > 0.05:
            object.__setattr__(self, "duration_seconds", computed_duration)
        return self


class SourceMediaMetadata(BaseModel):
    """Metadata of the processed source file."""
    filename: str
    format_name: str
    duration_seconds: float
    size_bytes: int
    video_streams_count: int
    audio_streams_count: int
    selected_audio_stream_index: int
    audio_codec: str
    audio_sample_rate: int
    audio_channels: int


class TranscriptionRunMetadata(BaseModel):
    """Operational details of the transcription run."""
    provider: str
    model: str
    language: Optional[str] = None
    language_probability: Optional[float] = None
    word_timestamps_enabled: bool = True
    parameters: Dict[str, Any] = Field(default_factory=dict)
    duration_processed_seconds: float


class TranscriptArtifact(BaseModel):
    """Documented JSON artifact schema for persisted transcripts (TechSpec Section 6 & PRD FR-03)."""
    schema_version: str = "v1.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_media: SourceMediaMetadata
    transcription: TranscriptionRunMetadata
    word_timestamps_available: bool
    segment_count: int
    total_words_count: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)
    segments: List[TranscriptSegment]
