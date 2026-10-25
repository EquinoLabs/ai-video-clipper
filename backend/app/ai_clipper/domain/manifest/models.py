"""Run manifest and clip metadata schemas."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from app.ai_clipper.domain.timeline.models import ClipTimeline


class SourceVideoReference(BaseModel):
    """Reference to the source video used for a run."""
    video_id: str = Field(..., description="Stable identity of the source video")
    normalized_name: str = Field(..., description="Normalized snake_case stem of the source video")
    source_path: str = Field(..., description="Path to the source video relative to workspace root")
    duration_seconds: float = Field(..., ge=0.0, description="Total source duration in seconds")


class ManifestLongClipItem(BaseModel):
    """Summary record of a long clip in the run manifest."""
    clip_id: str = Field(..., description="Unique long clip identifier (e.g., lng_001)")
    folder: str = Field(..., description="Relative folder path (e.g., long_clips/clip_01)")
    source_start_seconds: float = Field(..., ge=0.0)
    source_end_seconds: float = Field(..., ge=0.0)
    duration_seconds: float = Field(..., gt=0.0)
    score: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: Literal["draft", "clean_master_ready", "final_render_ready", "failed", "rejected", "approved"] = "draft"
    clean_master_path: Optional[str] = None
    final_render_path: Optional[str] = None
    short_clips_count: int = Field(default=0, ge=0)


class ManifestShortClipItem(BaseModel):
    """Summary record of a short clip in the run manifest."""
    clip_id: str = Field(..., description="Unique short clip identifier (e.g., srt_001)")
    parent_clip_id: str = Field(..., description="Parent long clip identifier (e.g., lng_001)")
    folder: str = Field(..., description="Relative folder path (e.g., short_clips/clip_01)")
    source_start_seconds: float = Field(..., ge=0.0)
    source_end_seconds: float = Field(..., ge=0.0)
    parent_local_start_seconds: float = Field(..., ge=0.0)
    parent_local_end_seconds: float = Field(..., ge=0.0)
    duration_seconds: float = Field(..., gt=0.0)
    score: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: Literal["draft", "clean_master_ready", "final_render_ready", "failed", "rejected", "approved"] = "draft"
    clean_master_path: Optional[str] = None
    final_render_path: Optional[str] = None


class RunManifest(BaseModel):
    """Canonical run manifest describing the entire pipeline execution."""
    schema_version: str = Field(default="v1.0", description="Manifest schema version")
    run_id: str = Field(..., description="Unique run identifier (e.g. run_20261024_210000_001)")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 creation timestamp",
    )
    timezone: str = Field(default="Asia/Kolkata", description="Configured timezone name")
    pipeline_mode: Literal["full", "long", "short"] = Field(
        default="full",
        description="Pipeline mode executed",
    )
    status: Literal["pending", "running", "awaiting_review", "completed", "failed"] = Field(
        default="running",
        description="Execution status of the entire run",
    )
    source_video: SourceVideoReference
    configuration: Dict[str, Any] = Field(
        default_factory=dict,
        description="Run configuration parameters (editorial_goal, caption_preset, etc.)",
    )
    stage_statuses: Dict[str, str] = Field(
        default_factory=dict,
        description="Status of individual stages (e.g., transcription: completed)",
    )
    long_clips: List[ManifestLongClipItem] = Field(
        default_factory=list,
        description="List of discovered/rendered long clips",
    )
    short_clips: List[ManifestShortClipItem] = Field(
        default_factory=list,
        description="List of discovered/rendered short clips",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="List of error messages encountered during run",
    )


class ClipFiles(BaseModel):
    """File artifacts associated with a clip."""
    clean_master: Optional[str] = None
    final_render: Optional[str] = None
    transcript: Optional[str] = None
    captions_ass: Optional[str] = None
    captions_srt: Optional[str] = None


class ClipMetadata(BaseModel):
    """Canonical metadata for an individual long or short clip."""
    schema_version: str = Field(default="v1.0", description="Clip metadata schema version")
    clip_id: str = Field(..., description="Clip identifier (e.g., lng_001 or srt_001)")
    clip_type: Literal["long", "short"] = Field(..., description="Type of clip")
    parent_id: Optional[str] = Field(
        None,
        description="Parent identifier (source video_id for long, long clip_id for short)",
    )
    parent_type: Literal["source_video", "long_clip"] = Field(
        ...,
        description="Type of parent container",
    )
    source_video_id: str = Field(..., description="Root source video identifier")
    timeline: ClipTimeline = Field(..., description="Explicit source and local timing coordinates")
    hook: Optional[str] = Field(None, description="Opening hook or rationale")
    overall_score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Overall ranking score")
    score_breakdown: Optional[Dict[str, float]] = Field(None, description="Sub-score breakdown")
    status: Literal["draft", "clean_master_ready", "final_render_ready", "failed", "rejected", "approved"] = "draft"
    rejection_reason: Optional[str] = Field(None, description="Reason if candidate or clip was rejected")
    files: ClipFiles = Field(default_factory=ClipFiles, description="Associated file artifacts")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 creation timestamp",
    )

    @model_validator(mode="after")
    def validate_lineage(self) -> "ClipMetadata":
        if self.clip_type == "long":
            if self.parent_type != "source_video":
                raise ValueError(
                    f"Long clip ({self.clip_id}) must have parent_type='source_video'; got '{self.parent_type}'"
                )
            if self.parent_id is not None and self.parent_id != self.source_video_id:
                raise ValueError(
                    f"Long clip parent_id ('{self.parent_id}') must match source_video_id ('{self.source_video_id}')"
                )
            if self.parent_id is None:
                object.__setattr__(self, "parent_id", self.source_video_id)
        elif self.clip_type == "short":
            if self.parent_type != "long_clip":
                raise ValueError(
                    f"Short clip ({self.clip_id}) must have parent_type='long_clip'; got '{self.parent_type}'"
                )
            if not self.parent_id or not self.parent_id.strip():
                raise ValueError(
                    f"Short clip ({self.clip_id}) must have a valid non-empty parent_id referencing a parent long clip"
                )
        return self
