"""API schemas for jobs and stage runs."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_QUEUED = "retry_queued"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class StageName(str, Enum):
    MEDIA_VALIDATION = "media_validation"
    AUDIO_EXTRACTION = "audio_extraction"
    TRANSCRIPTION = "transcription"
    TRANSCRIPT_NORMALIZATION = "transcript_normalization"
    CANDIDATE_GENERATION = "candidate_generation"
    CANDIDATE_VALIDATION_RANKING = "candidate_validation_ranking"
    CANDIDATE_VISUAL_ANALYSIS = "candidate_visual_analysis"
    CLIP_RENDERING = "clip_rendering"
    OUTPUT_VALIDATION = "output_validation"
    OUTPUT_UPLOAD_FINALIZATION = "output_upload_finalization"


class StageRunSummary(BaseModel):
    stage: StageName
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress: float = 0.0
    error_code: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    project_id: str
    status: JobStatus
    current_stage: Optional[StageName] = None
    progress: float = Field(0.0, ge=0.0, le=1.0)
    stages: List[StageRunSummary] = Field(default_factory=list)
    retryable: bool = False
    error: Optional[Dict[str, Any]] = None
