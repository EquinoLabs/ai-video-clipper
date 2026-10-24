"""LLM evaluation and discovery provider interface."""

from abc import ABC, abstractmethod
from typing import List, Optional, Union
from app.api.v1.schemas.candidates import (
    EditorialGoal,
    GenerationSettings,
    LLMAnchorEvaluation,
    LLMCandidateEvaluation,
)
from app.services.transcription.base import TranscriptSegment


class LLMProvider(ABC):
    """Abstract interface for LLM candidate discovery and evaluation."""

    @abstractmethod
    async def discover_and_evaluate(
        self,
        transcript_segments: List[TranscriptSegment],
        editorial_goal: EditorialGoal,
        settings: GenerationSettings,
        custom_instructions: Optional[str] = None,
        target_count: Optional[int] = None,
        is_long_clip: bool = False,
    ) -> List[Union[LLMCandidateEvaluation, LLMAnchorEvaluation]]:
        """Analyze transcript chunk and return structured candidate or anchor evaluations.
        
        When is_long_clip=True, returns List[LLMCandidateEvaluation].
        When is_long_clip=False, returns List[LLMAnchorEvaluation].
        """
        pass
