"""Ingestion domain models and metadata schema."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IngestionMetadata(BaseModel):
    """Normalized metadata for an ingested source video."""
    schema_version: str = Field(default="v1.0", description="Schema version of ingestion metadata")
    video_id: str = Field(..., description="Stable generated video identity")
    original_filename: str = Field(..., description="Original filename prior to normalization")
    stored_filename: str = Field(..., description="Normalized stored filename")
    ingested_at: str = Field(..., description="ISO 8601 timestamp with timezone")
    ingestion_date: str = Field(..., description="Ingestion date formatted YYYY-MM-DD")
    file_size_bytes: int = Field(..., ge=0, description="File size in bytes")
    media_type: Optional[str] = Field(None, description="Media MIME type or file extension")
    content_sha256: Optional[str] = Field(None, description="SHA-256 hash of file content")
    source_path: str = Field(..., description="Relative path from project/managed root")
    probe_status: str = Field(default="pending", description="Status of media probing: 'probed', 'failed', 'pending'")
    media_info: Optional[Dict[str, Any]] = Field(None, description="Media probe information (duration, codecs, resolution)")
