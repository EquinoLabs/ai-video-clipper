"""Schemas for Phase 3 review API."""

from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from app.ai_clipper.api.schemas.candidates import (
    CandidateListItem,
    EditorialGoal,
    ScoreBreakdown,
    ValidationStatus,
)


class RenderedClipInfo(BaseModel):
    """Metadata regarding the rendered MP4 clip artifact."""
    is_rendered: bool
    clip_filename: Optional[str] = None
    video_url: Optional[str] = None
    download_url: Optional[str] = None
    ass_subtitle_url: Optional[str] = None
    srt_subtitle_url: Optional[str] = None
    file_size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ReviewCandidateItem(BaseModel):
    """Enhanced candidate item for frontend review and playback."""
    id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    hook: str
    transcript_excerpt: str
    editorial_goal: EditorialGoal
    overall_score: int
    score_breakdown: ScoreBreakdown
    rationale: str
    evidence_quotes: List[str] = Field(default_factory=list)
    confidence_label: str
    validation_status: ValidationStatus
    render_info: RenderedClipInfo


class ReviewRunSummary(BaseModel):
    """Summary of a local processing run."""
    run_id: str
    source_filename: str
    source_duration_seconds: float
    editorial_goal: EditorialGoal
    created_at: str
    total_candidates: int
    rendered_candidates: int


class ReviewDetailResponse(BaseModel):
    """Response containing full review data for a run."""
    summary: ReviewRunSummary
    candidates: List[ReviewCandidateItem]


class CaptionStyleResponse(BaseModel):
    """API schema for caption style preset definition and browser preview styling."""
    style_id: str
    display_name: str
    description: str
    sample_text: str
    preview_css: dict
