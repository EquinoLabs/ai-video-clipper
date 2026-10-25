"""Visual framing analysis and configuration interface."""

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class FramingMode(str, Enum):
    CENTER_CROP = "center_crop"
    FIT_BACKGROUND = "fit_background"
    ACTIVE_SPEAKER_CROP = "active_speaker_crop"
    TWO_PERSON_STACKED = "two_person_stacked"
    MANUAL_OVERRIDE = "manual_override"


class CropWindow(BaseModel):
    """Normalized coordinates within 0.0 - 1.0 bounding space."""
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    width: float = Field(..., gt=0.0, le=1.0)
    height: float = Field(..., gt=0.0, le=1.0)


class FramingConfig(BaseModel):
    mode: FramingMode = FramingMode.CENTER_CROP
    config_version: str = "v1.0"
    crop_window_normalized: Optional[CropWindow] = None
    manual_override: bool = False


class FramingAnalyzer(ABC):
    """Abstract interface for candidate-range visual analysis."""

    @abstractmethod
    async def analyze_range(
        self,
        video_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> FramingConfig:
        """Analyze sampled video frames and suggest optimal vertical framing."""
        pass
