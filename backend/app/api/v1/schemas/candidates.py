"""Domain and API schemas for candidate moments and generation."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class EditorialGoal(str, Enum):
    OVERALL = "overall"
    HUMOR = "humor"
    EDUCATION = "education"
    EMOTION = "emotion"
    THOUGHT_PROVOKING = "thought_provoking"
    HOOK = "hook"
    CUSTOM = "custom"


class ConfidenceLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ValidationStatus(str, Enum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class ValidationReasonCode(str, Enum):
    """Typed reason codes for candidate validation checks."""
    START_NEGATIVE = "START_NEGATIVE"
    END_EXCEEDS_SOURCE = "END_EXCEEDS_SOURCE"
    DURATION_NON_POSITIVE = "DURATION_NON_POSITIVE"
    DURATION_BELOW_MINIMUM = "DURATION_BELOW_MINIMUM"
    DURATION_EXCEEDS_MAXIMUM = "DURATION_EXCEEDS_MAXIMUM"
    NO_EVIDENCE = "NO_EVIDENCE"
    EVIDENCE_NOT_GROUNDED = "EVIDENCE_NOT_GROUNDED"
    EVIDENCE_PARTIALLY_UNGROUNDED = "EVIDENCE_PARTIALLY_UNGROUNDED"
    UNKNOWN_SEGMENT_ID = "UNKNOWN_SEGMENT_ID"
    DISCONTIGUOUS_ANCHOR = "DISCONTIGUOUS_ANCHOR"
    EXCERPT_NOT_GROUNDED = "EXCERPT_NOT_GROUNDED"
    NO_VALID_WINDOW = "NO_VALID_WINDOW"


class CandidateStatus(str, Enum):
    SUGGESTED = "suggested"
    SELECTED = "selected"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class EvidenceItem(BaseModel):
    """Timestamped quote from transcript grounding the candidate."""
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., ge=0)
    quote: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "EvidenceItem":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class ScoreBreakdown(BaseModel):
    """Raw dimension ratings on common scale (0-5) per TechSpec Section 5."""
    hook_strength: float = Field(..., ge=0.0, le=5.0)
    completeness_coherence: float = Field(..., ge=0.0, le=5.0)
    standalone_understandability: float = Field(..., ge=0.0, le=5.0)
    goal_relevance: float = Field(..., ge=0.0, le=5.0)
    goal_specific_impact: float = Field(..., ge=0.0, le=5.0)
    specificity_insight: float = Field(..., ge=0.0, le=5.0)
    pacing_conciseness: float = Field(..., ge=0.0, le=5.0)
    ending_quality: float = Field(..., ge=0.0, le=5.0)


class QualitativeAssessment(BaseModel):
    rating: float = Field(..., ge=0.0, le=5.0)
    explanation: str = Field(..., min_length=1)


class GenerationSettings(BaseModel):
    """Configurable duration and count bounds for candidate generation."""
    min_duration_seconds: float = Field(default=10.0, ge=5.0)
    preferred_min_seconds: float = Field(default=15.0, ge=5.0)
    preferred_max_seconds: float = Field(default=45.0, le=300.0)
    target_duration_seconds: float = Field(default=30.0)
    max_duration_seconds: float = Field(default=60.0, le=300.0)
    candidate_pool_target: int = Field(default=10, ge=1, le=50)
    display_limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_bounds(self) -> "GenerationSettings":
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("min_duration_seconds cannot exceed max_duration_seconds")
        if not (self.min_duration_seconds <= self.preferred_min_seconds <= self.preferred_max_seconds <= self.max_duration_seconds):
            raise ValueError("Duration hierarchy violated: min <= preferred_min <= preferred_max <= max")
        return self

    @classmethod
    def for_long_clips(
        cls,
        min_duration_seconds: float = 30.0,
        preferred_min_seconds: float = 45.0,
        preferred_max_seconds: float = 120.0,
        target_duration_seconds: float = 90.0,
        max_duration_seconds: float = 180.0,
        candidate_pool_target: int = 10,
        display_limit: int = 10,
    ) -> "GenerationSettings":
        """Factory for long-clip candidate discovery settings (30s - 180s, target 90s)."""
        return cls(
            min_duration_seconds=min_duration_seconds,
            preferred_min_seconds=preferred_min_seconds,
            preferred_max_seconds=preferred_max_seconds,
            target_duration_seconds=target_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            candidate_pool_target=candidate_pool_target,
            display_limit=display_limit,
        )

    @classmethod
    def for_short_clips(
        cls,
        min_duration_seconds: float = 10.0,
        preferred_min_seconds: float = 15.0,
        preferred_max_seconds: float = 45.0,
        target_duration_seconds: float = 30.0,
        max_duration_seconds: float = 60.0,
        candidate_pool_target: int = 10,
        display_limit: int = 10,
    ) -> "GenerationSettings":
        """Factory for short-clip candidate discovery settings (10s - 60s, target 30s)."""
        return cls(
            min_duration_seconds=min_duration_seconds,
            preferred_min_seconds=preferred_min_seconds,
            preferred_max_seconds=preferred_max_seconds,
            target_duration_seconds=target_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            candidate_pool_target=candidate_pool_target,
            display_limit=display_limit,
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


class CandidateListItem(BaseModel):
    """API-facing summary of a candidate moment in project clip list."""
    id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    hook: str
    transcript_excerpt: str
    editorial_goal: EditorialGoal
    overall_score: int = Field(..., ge=0, le=100)
    score_breakdown: ScoreBreakdown
    rationale: str
    evidence: List[EvidenceItem]
    confidence_label: ConfidenceLabel
    validation_status: ValidationStatus
    selected: bool
    status: CandidateStatus
    user_edited: bool = False


class CandidateResponse(CandidateListItem):
    """Detailed candidate representation including assessments."""
    candidate_id: Optional[str] = None
    hook_assessment: Optional[QualitativeAssessment] = None
    completeness_assessment: Optional[QualitativeAssessment] = None
    goal_impact_assessment: Optional[QualitativeAssessment] = None
    scoring_version: str = "v1.0"


class LLMCandidateEvaluation(BaseModel):
    """Schema for raw structured LLM evaluation output.
    Note: Does NOT contain overall_score or duration_seconds; the backend
    authoritatively derives duration and calculates overall_score from dimensions.
    """
    start_seconds: float = Field(..., ge=0.0)
    end_seconds: float = Field(..., ge=0.0)
    hook: str
    transcript_excerpt: str
    score_dimensions: ScoreBreakdown
    rationale: str
    evidence: List[EvidenceItem]
    confidence_label: ConfidenceLabel


class AnchorType(str, Enum):
    """Categorical classification of a semantic anchor moment."""
    PUNCHLINE = "punchline"
    COMEDIC_BANTER = "comedic_banter"
    STORY_CLIMAX = "story_climax"
    PROVOCATIVE_HOOK = "provocative_hook"
    INSIGHT = "insight"
    EMOTIONAL_REACTION = "emotional_reaction"


class LLMAnchorEvaluation(BaseModel):
    """Semantic anchor emitted by the LLM during short discovery.
    Identifies interesting moments by chunk-local transcript segment IDs rather than timestamps.
    """
    anchor_id: str = Field(..., min_length=1, description="Unique anchor ID within response, e.g. 'anc_001'")
    anchor_segment_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Contiguous list of chunk-local segment indices containing the anchor",
    )
    anchor_type: AnchorType = Field(
        default=AnchorType.PUNCHLINE,
        description="Categorical type of the anchor moment",
    )
    hook: str = Field(..., min_length=3, description="Editorial hook description")
    transcript_excerpt: str = Field(..., min_length=3, description="Verbatim quote of the anchor core moment")
    score_dimensions: ScoreBreakdown = Field(..., description="Ratings across 8 dimensions (0.0 to 5.0)")
    rationale: str = Field(..., min_length=5, description="Editorial rationale for why this moment is compelling")
    evidence: List[EvidenceItem] = Field(..., min_length=1, description="Direct quote excerpts grounding the anchor")
    confidence_label: ConfidenceLabel = Field(default=ConfidenceLabel.HIGH)
