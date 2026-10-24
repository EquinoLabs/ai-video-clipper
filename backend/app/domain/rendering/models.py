"""Models and schemas for video rendering, caption styling, and output validation."""

from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class FramingMode(str, Enum):
    CENTER_CROP = "center_crop"
    # FIT_BACKGROUND = "fit_background"  # Phase 5
    # SMART_REFRAME = "smart_reframe"   # Phase 6


class FramingConfig(BaseModel):
    mode: FramingMode = FramingMode.CENTER_CROP
    config_version: str = "v1.0"


class CaptionPosition(BaseModel):
    x: float = Field(default=0.5, ge=0.0, le=1.0, description="Normalized X coordinate (0.5=center)")
    y: float = Field(default=0.8, ge=0.0, le=1.0, description="Normalized Y coordinate (0.8=lower third safe area)")
    coordinate_space: Literal["normalized_canvas"] = "normalized_canvas"


class CaptionShadow(BaseModel):
    color: str = "&H80000000"  # ASS format: &HAABBGGRR (semi-transparent black)
    offset_x: float = 1.5
    offset_y: float = 1.5


class CaptionOutline(BaseModel):
    color: str = "&H00000000"  # ASS format: opaque black
    width: float = 2.0


class CaptionConfig(BaseModel):
    """Configuration for subtitle generation and styling (TechSpec Section 8)."""
    preset_id: str = "default_bold_v1"
    config_version: str = "v1.0"
    font_family: str = "Arial"
    font_size: int = Field(default=48, ge=16, le=120, description="Font size for 1080x1920 canvas")
    font_weight: str = "Bold"
    text_color: str = "&H00FFFFFF"  # White in ASS (&HAABBGGRR)
    highlight_color: Optional[str] = "&H0000FFFF"  # Yellow in ASS
    border_style: int = Field(default=1, description="ASS BorderStyle: 1=Outline+Shadow, 3=Opaque Box")
    box_color: Optional[str] = Field(default="&H80000000", description="ASS box background color if border_style=3")
    outline: Optional[CaptionOutline] = Field(default_factory=CaptionOutline)
    shadow: Optional[CaptionShadow] = Field(default_factory=CaptionShadow)
    alignment: int = Field(default=2, description="ASS alignment: 2=bottom-center")
    position: CaptionPosition = Field(default_factory=CaptionPosition)
    max_words_per_line: int = Field(default=5, ge=1, le=12)
    max_lines_per_cue: int = Field(default=2, ge=1, le=3)
    timing_mode: Literal["phrase", "word"] = "phrase"
    uppercase: bool = Field(default=False, description="Whether to transform caption text to uppercase")


class OutputConfig(BaseModel):
    """Output video and audio encoding configuration (TechSpec Section 8)."""
    aspect_ratio: Literal["9:16"] = "9:16"
    width: int = 1080
    height: int = 1920
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    crf: int = Field(default=20, ge=0, le=51)
    preset: str = "fast"
    pixel_format: str = "yuv420p"
    container: Literal["mp4"] = "mp4"


class RenderValidationResult(BaseModel):
    """Results of output media validation checks (PRD FR-08, TechSpec Section 8)."""
    is_valid: bool
    output_path: Path
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    has_audio: bool
    validation_errors: List[str] = Field(default_factory=list)
