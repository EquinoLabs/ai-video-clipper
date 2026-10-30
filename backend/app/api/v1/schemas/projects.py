"""API schemas for projects, assets, and uploads."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    UPLOAD_PENDING = "upload_pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ProjectCreateResponse(BaseModel):
    project_id: str
    status: ProjectStatus


class UploadInitiateRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    size_bytes: int = Field(..., gt=0)
    content_type: str = Field(..., min_length=3)


class UploadInitiateResponse(BaseModel):
    asset_id: str
    upload_url: str
    required_headers: dict = Field(default_factory=dict)
    expires_at: datetime


class CompleteUploadResponse(BaseModel):
    asset_id: str
    status: str
    job_id: Optional[str] = None
