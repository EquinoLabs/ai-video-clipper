"""OpenAI LLM adapter for structured candidate moment discovery."""

import json
import logging
import os
from typing import List, Optional, Union
from pydantic import BaseModel, Field

from app.ai_clipper.domain.candidates.models import (
    EditorialGoal,
    GenerationSettings,
    LLMAnchorEvaluation,
    LLMCandidateEvaluation,
)
from app.core.config import get_settings
from app.ai_clipper.domain.transcript.models import TranscriptSegment
from app.ai_clipper.services.llm.base import LLMProvider
from app.ai_clipper.services.llm.chunking import format_segments_to_text
from app.ai_clipper.services.llm.models import (
    LLMAnchorsResponseEnvelope,
    LLMCandidatesResponseEnvelope,
)
from app.ai_clipper.services.llm.prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class OpenAIProviderError(Exception):
    """Exception raised for OpenAI API and parsing errors."""
    pass


class OpenAIProvider(LLMProvider):
    """Adapter for OpenAI models supporting structured outputs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[object] = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.llm_api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or settings.llm_model or "gpt-4o-mini"
        self._client = client

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise OpenAIProviderError(
                    "OpenAI API key not configured. Set OPENAI_API_KEY in environment or .env."
                )
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError as exc:
                raise OpenAIProviderError("The 'openai' package is not installed.") from exc
        return self._client

    async def discover_and_evaluate(
        self,
        transcript_segments: List[TranscriptSegment],
        editorial_goal: EditorialGoal,
        settings: GenerationSettings,
        custom_instructions: Optional[str] = None,
        target_count: Optional[int] = None,
        is_long_clip: bool = False,
    ) -> List[Union[LLMCandidateEvaluation, LLMAnchorEvaluation]]:
        """Call OpenAI with structured JSON outputs and return validated candidate or anchor evaluations."""
        if not transcript_segments:
            return []

        formatted_text = format_segments_to_text(transcript_segments, is_anchor_mode=not is_long_clip)
        system_prompt = build_system_prompt(editorial_goal, settings, is_long_clip=is_long_clip)
        user_prompt = build_user_prompt(
            formatted_transcript=formatted_text,
            custom_instructions=custom_instructions,
            target_count=target_count,
            is_long_clip=is_long_clip,
        )

        client = self._get_client()

        logger.info(
            f"Calling OpenAI model '{self.model}' for {'long candidate' if is_long_clip else 'short anchor'} discovery "
            f"({len(transcript_segments)} segments, goal={editorial_goal.value})..."
        )

        response_format = LLMCandidatesResponseEnvelope if is_long_clip else LLMAnchorsResponseEnvelope

        try:
            # Use OpenAI beta.chat.completions.parse for Pydantic structured output
            completion = client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_format,
                temperature=0.3,
            )
            parsed_envelope = completion.choices[0].message.parsed
            if parsed_envelope is None:
                # If refusal or empty response occurred
                refusal = getattr(completion.choices[0].message, "refusal", None)
                if refusal:
                    raise OpenAIProviderError(f"OpenAI refused candidate generation: {refusal}")
                return []

            if is_long_clip:
                logger.info(
                    f"OpenAI returned {len(parsed_envelope.candidates)} raw candidate moments."
                )
                return parsed_envelope.candidates
            else:
                logger.info(
                    f"OpenAI returned {len(parsed_envelope.anchors)} raw semantic anchors."
                )
                return parsed_envelope.anchors

        except Exception as exc:
            if isinstance(exc, OpenAIProviderError):
                raise
            logger.error(f"OpenAI candidate discovery failed: {exc}", exc_info=True)
            raise OpenAIProviderError(f"OpenAI candidate evaluation failed: {exc}") from exc
