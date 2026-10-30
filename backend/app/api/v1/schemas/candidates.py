# Domain and API schemas for candidate moments and generation.

from typing import List, Optional
from pydantic import BaseModel, Field

# Re-export domain models from canonical domain package
from app.domain.candidates.models import (
    EditorialGoal,
    ConfidenceLabel,
    ValidationStatus,
    ValidationReasonCode,
    CandidateStatus,
    EvidenceItem,
    ScoreBreakdown,
    QualitativeAssessment,
    GenerationSettings,
    CandidateListItem,
    LLMCandidateEvaluation,
    AnchorType,
    LLMAnchorEvaluation,
)


class CandidateGenerationRequest(BaseModel):
    """Request payload to initiate candidate discovery and ranking."""
    editorial_goal: EditorialGoal = EditorialGoal.OVERALL
    custom_instructions: Optional[str] = None
    settings: GenerationSettings = Field(default_factory=GenerationSettings)
    idempotency_key: Optional[str] = None


class CandidateUpdateRequest(BaseModel):
    """Payload for user edits to a candidate moment."""
    start_seconds: Optional[float] = Field(None, ge=0.0)
    end_seconds: Optional[float] = Field(None, ge=0.0)
    selected: Optional[bool] = None
    status: Optional[CandidateStatus] = None


class CandidateResponse(CandidateListItem):
    """Detailed candidate representation including assessments."""
    candidate_id: Optional[str] = None
    hook_assessment: Optional[QualitativeAssessment] = None
    completeness_assessment: Optional[QualitativeAssessment] = None
    goal_impact_assessment: Optional[QualitativeAssessment] = None
    scoring_version: str = "v1.0"
