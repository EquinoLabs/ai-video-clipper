"""Candidate artifact models and atomic serialization."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.api.v1.schemas.candidates import (
    CandidateListItem,
    EditorialGoal,
    GenerationSettings,
    ValidationReasonCode,
)
from app.domain.transcript.models import SourceMediaMetadata


class RejectedCandidateAudit(BaseModel):
    """Audit record for a candidate moment rejected during validation."""
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    hook: str
    reason_codes: List[ValidationReasonCode]
    reasons: List[str]


class CandidateGenerationMetadata(BaseModel):
    """Metadata describing candidate discovery run parameters."""
    editorial_goal: EditorialGoal
    custom_instructions: Optional[str] = None
    provider: str
    model: str
    scoring_version: str = "v1.0"
    settings: GenerationSettings
    chunks_processed: int = 1
    total_raw_candidates: int = 0
    rejected_candidates: List[RejectedCandidateAudit] = Field(default_factory=list)


class CandidateArtifact(BaseModel):
    """Canonical artifact model persisted as candidates.json."""
    schema_version: str = Field(default="v1.0", description="Artifact schema version")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 generation timestamp",
    )
    source_media: SourceMediaMetadata
    generation: CandidateGenerationMetadata
    candidates_count: int
    candidates: List[CandidateListItem]


def write_candidate_artifact(artifact: CandidateArtifact, output_path: Path) -> Path:
    """Atomically write candidate artifact to disk with indented formatting."""
    resolved_path = Path(output_path).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = resolved_path.with_suffix(".tmp")
    serialized_json = artifact.model_dump_json(indent=2)

    temp_path.write_text(serialized_json, encoding="utf-8")
    temp_path.replace(resolved_path)
    return resolved_path
