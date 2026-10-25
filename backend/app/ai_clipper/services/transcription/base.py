"""Abstract transcription provider interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from app.ai_clipper.domain.transcript.models import TranscriptSegment, WordTiming


class TranscriptionResult(BaseModel):
    """Normalized output from any transcription adapter."""
    segments: List[TranscriptSegment]
    language: Optional[str] = None
    language_probability: Optional[float] = None
    duration_seconds: float
    word_timestamps_available: bool = False
    provider: str
    model: str
    warnings: List[str] = Field(default_factory=list)


class TranscriptionProviderError(Exception):
    """Base exception for transcription provider errors."""
    pass


class TranscriptionProvider(ABC):
    """Interface for transcription adapters (Faster-Whisper, OpenAI Whisper, API providers)."""

    @abstractmethod
    def transcribe(
        self,
        audio_file_path: Path,
        word_timestamps: bool = True,
        language: Optional[str] = None,
        max_duration_seconds: Optional[float] = None,
    ) -> TranscriptionResult:
        """Transcribe an extracted audio file into normalized segments."""
        pass
