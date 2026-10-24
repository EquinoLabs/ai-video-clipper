"""Shared data models and response envelopes for LLM provider adapters."""

from typing import List
from pydantic import BaseModel, Field

from app.api.v1.schemas.candidates import LLMAnchorEvaluation, LLMCandidateEvaluation


class LLMCandidatesResponseEnvelope(BaseModel):
    """Envelope model for structured candidate evaluation output (long-clip discovery)."""
    candidates: List[LLMCandidateEvaluation] = Field(default_factory=list)


class LLMAnchorsResponseEnvelope(BaseModel):
    """Envelope model for structured semantic anchor evaluation output (short-clip discovery)."""
    anchors: List[LLMAnchorEvaluation] = Field(default_factory=list)

