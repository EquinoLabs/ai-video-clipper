"""Ollama local LLM adapter for structured candidate moment discovery."""

import copy
import json
import logging
from typing import Any, List, Optional, Union
import httpx
from pydantic import ValidationError

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


class OllamaProviderError(Exception):
    """Exception raised for Ollama connectivity, execution, and parsing errors."""
    pass


class OllamaProvider(LLMProvider):
    """Adapter for locally running Ollama models supporting structured JSON outputs."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        settings = get_settings()
        raw_url = base_url or settings.ollama_base_url or "http://localhost:11434"
        self.base_url = raw_url.rstrip("/")
        self.model = model or settings.ollama_model or "qwen2.5:7b"
        self.timeout_seconds = timeout_seconds or settings.ollama_timeout_seconds or 300.0
        self._client = client

    async def _post_chat(self, payload: dict) -> dict:
        """Execute HTTP POST to Ollama /api/chat with error mapping."""
        chat_endpoint = f"{self.base_url}/api/chat"

        try:
            if self._client is not None:
                response = await self._client.post(
                    chat_endpoint,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        chat_endpoint,
                        json=payload,
                        timeout=self.timeout_seconds,
                    )

            if response.status_code == 404:
                # Typically missing model error or invalid endpoint
                err_detail = ""
                try:
                    err_json = response.json()
                    err_detail = err_json.get("error", "")
                except Exception:
                    err_detail = response.text

                if "not found" in err_detail.lower():
                    raise OllamaProviderError(
                        f"Model '{self.model}' not found on Ollama at '{self.base_url}'. "
                        f"Verify available models via `ollama list` or pull it using `ollama pull {self.model}`."
                    )
                raise OllamaProviderError(
                    f"Ollama endpoint '{chat_endpoint}' returned 404 Not Found: {err_detail}"
                )

            if response.is_error:
                err_msg = response.text
                try:
                    err_json = response.json()
                    err_msg = err_json.get("error", response.text)
                except Exception:
                    pass
                raise OllamaProviderError(
                    f"Ollama API returned HTTP {response.status_code}: {err_msg}"
                )

            return response.json()

        except httpx.ConnectError as exc:
            raise OllamaProviderError(
                f"Ollama service unavailable at '{self.base_url}'. "
                f"Ensure Ollama is installed and running (`ollama serve`)."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaProviderError(
                f"Ollama request timed out after {self.timeout_seconds:.1f}s for model '{self.model}'. "
                f"Consider increasing OLLAMA_TIMEOUT_SECONDS."
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaProviderError(
                f"Network request to Ollama failed: {exc}"
            ) from exc

    async def discover_and_evaluate(
        self,
        transcript_segments: List[TranscriptSegment],
        editorial_goal: EditorialGoal,
        settings: GenerationSettings,
        custom_instructions: Optional[str] = None,
        target_count: Optional[int] = None,
        is_long_clip: bool = False,
    ) -> List[Union[LLMCandidateEvaluation, LLMAnchorEvaluation]]:
        """Call local Ollama instance with structured JSON output.
        
        When is_long_clip=True: returns List[LLMCandidateEvaluation] (timestamp-based).
        When is_long_clip=False: returns List[LLMAnchorEvaluation] (segment ID-based anchors).
        """
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

        schema = (
            LLMCandidatesResponseEnvelope.model_json_schema()
            if is_long_clip
            else LLMAnchorsResponseEnvelope.model_json_schema()
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": schema,
            "options": {
                "temperature": 0.2,
                "num_ctx": 8192,
            },
        }

        logger.info(
            f"Calling Ollama model '{self.model}' at {self.base_url} for "
            f"{'long candidate' if is_long_clip else 'short anchor'} discovery "
            f"({len(transcript_segments)} segments, goal={editorial_goal.value})..."
        )

        response_data = await self._post_chat(payload)

        # Parse message content
        message_content = response_data.get("message", {}).get("content", "")
        if not message_content or not message_content.strip():
            logger.warning(f"Ollama model '{self.model}' returned an empty message content.")
            return []

        try:
            parsed_raw = json.loads(message_content)
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse Ollama output as JSON: {exc}")
            raise OllamaProviderError(
                f"Malformed JSON returned by Ollama model '{self.model}': {exc}"
            ) from exc

        return self._sanitize_and_validate_response(
            parsed_raw=parsed_raw,
            is_long_clip=is_long_clip,
        )

    def _sanitize_and_validate_response(
        self,
        parsed_raw: Any,
        is_long_clip: bool,
    ) -> List[Union[LLMCandidateEvaluation, LLMAnchorEvaluation]]:
        """Normalize, sanitize malformed evidence timestamps, and validate candidate envelopes.

        Preserves strict schema validation for all candidate fields. When an evidence item
        contains end_seconds <= start_seconds, that specific item is discarded rather than
        failing the entire candidate response. If a candidate is left with no acceptable evidence,
        it is rejected with diagnostic logging.
        """
        # Deep copy to ensure no unexpected mutation of caller's data
        data = copy.deepcopy(parsed_raw)

        # 1. Extract raw items list based on clip mode and envelope type
        if is_long_clip:
            if isinstance(data, list):
                raw_items = data
            elif isinstance(data, dict):
                if "candidates" in data and isinstance(data["candidates"], list):
                    raw_items = data["candidates"]
                elif any(k in data for k in ("start_seconds", "hook", "transcript_excerpt")):
                    raw_items = [data]
                else:
                    raw_items = []
            else:
                raise OllamaProviderError(
                    f"Unexpected JSON root type from Ollama: {type(data).__name__} (expected object or list)"
                )
        else:
            if isinstance(data, list):
                raw_items = data
            elif isinstance(data, dict):
                if "anchors" in data and isinstance(data["anchors"], list):
                    raw_items = data["anchors"]
                elif "candidates" in data and isinstance(data["candidates"], list):
                    raw_items = data["candidates"]
                elif any(k in data for k in ("anchor_id", "anchor_segment_ids", "hook")):
                    raw_items = [data]
                else:
                    raw_items = []
            else:
                raise OllamaProviderError(
                    f"Unexpected JSON root type from Ollama: {type(data).__name__} (expected object or list)"
                )

        if not raw_items:
            logger.info(f"Ollama model '{self.model}' returned 0 candidate moments.")
            return []

        total_raw_count = len(raw_items)
        surviving_items: List[Any] = []
        rejected_diagnostics: List[str] = []

        # 2. Individual evidence inspection and recovery
        for idx, item in enumerate(raw_items):
            if not isinstance(item, dict):
                # Non-dict item preserved to trigger strict Pydantic ValidationError below
                surviving_items.append(item)
                continue

            item_id = item.get("anchor_id") or item.get("hook") or f"index_{idx + 1}"

            if "evidence" in item and isinstance(item["evidence"], list):
                original_evidence_count = len(item["evidence"])
                valid_evidence: List[Any] = []
                discarded_count = 0

                for ev_idx, ev in enumerate(item["evidence"]):
                    if isinstance(ev, dict):
                        start_sec = ev.get("start_seconds")
                        end_sec = ev.get("end_seconds")
                        if start_sec is not None and end_sec is not None:
                            try:
                                start_f = float(start_sec)
                                end_f = float(end_sec)
                                if end_f <= start_f:
                                    logger.warning(
                                        f"Discarding malformed evidence item [{ev_idx}] for candidate '{item_id}': "
                                        f"end_seconds ({end_f}) <= start_seconds ({start_f})"
                                    )
                                    discarded_count += 1
                                    continue
                            except (ValueError, TypeError):
                                pass
                    valid_evidence.append(ev)

                if discarded_count > 0:
                    if len(valid_evidence) == 0:
                        diag = (
                            f"Candidate '{item_id}' (index {idx}) rejected: all {original_evidence_count} evidence item(s) "
                            f"had invalid timestamps (end_seconds <= start_seconds) and were discarded, leaving no acceptable evidence."
                        )
                        logger.warning(diag)
                        rejected_diagnostics.append(diag)
                        continue
                    else:
                        item["evidence"] = valid_evidence
                        logger.info(
                            f"Candidate '{item_id}' (index {idx}): recovered with {len(valid_evidence)}/{original_evidence_count} valid evidence items."
                        )

            surviving_items.append(item)

        # 3. Fail clearly if all candidates were rejected
        if total_raw_count > 0 and len(surviving_items) == 0:
            err_msg = (
                f"All {total_raw_count} candidate(s) failed validation: "
                + "; ".join(rejected_diagnostics)
            )
            logger.error(err_msg)
            raise OllamaProviderError(err_msg)

        if rejected_diagnostics:
            logger.info(
                f"Candidate evidence recovery: {len(surviving_items)}/{total_raw_count} candidates preserved "
                f"({len(rejected_diagnostics)} rejected due to lack of valid evidence)."
            )

        # 4. Strictly validate recovered items against the existing schema envelope
        try:
            if is_long_clip:
                envelope = LLMCandidatesResponseEnvelope.model_validate({"candidates": surviving_items})
                logger.info(f"Ollama returned {len(envelope.candidates)} raw candidate moments.")
                return envelope.candidates
            else:
                try:
                    anchor_envelope = LLMAnchorsResponseEnvelope.model_validate({"anchors": surviving_items})
                    logger.info(f"Ollama returned {len(anchor_envelope.anchors)} raw semantic anchors.")
                    return anchor_envelope.anchors
                except ValidationError:
                    cand_envelope = LLMCandidatesResponseEnvelope.model_validate({"candidates": surviving_items})
                    logger.info(f"Ollama returned {len(cand_envelope.candidates)} raw candidate moments.")
                    return cand_envelope.candidates
        except ValidationError as exc:
            logger.error(f"Ollama response failed Pydantic schema validation: {exc}")
            raise OllamaProviderError(
                f"Ollama model output failed schema validation: {exc}"
            ) from exc
