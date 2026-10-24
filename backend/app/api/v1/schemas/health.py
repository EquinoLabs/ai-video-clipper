"""Health check schemas."""

from datetime import datetime, timezone
from typing import Dict
from pydantic import BaseModel, Field


class SubsystemStatus(BaseModel):
    configured: bool
    status: str
    details: str


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str = Field(default="ok", description="Overall system health status")
    environment: str
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ffmpeg_available: bool
    subsystems: Dict[str, SubsystemStatus]
