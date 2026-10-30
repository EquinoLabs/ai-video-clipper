"""Generic structured JSON output generator over configured LLM providers.

Provides schema-enforced, validated structured JSON generation without coupling to
Clipper candidate evaluation schemas or modifying the existing LLMProvider interface.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex to strip markdown code blocks from LLM outputs
_CODE_BLOCK_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


class StructuredOutputError(Exception):
    """Base exception for structured output generation failures."""
    pass


class UnsupportedProviderError(StructuredOutputError):
    """Raised when an unsupported provider name is specified."""
    pass


class LLMCommunicationError(StructuredOutputError):
    """Raised on network, timeout, or HTTP communication errors with LLM provider."""
    pass


class MalformedJSONError(StructuredOutputError):
    """Raised when LLM output cannot be parsed as valid JSON."""
    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


class SchemaValidationError(StructuredOutputError):
    """Raised when JSON parses but fails Pydantic schema validation."""
    def __init__(self, message: str, raw_output: str, validation_errors: Any):
        super().__init__(message)
        self.raw_output = raw_output
        self.validation_errors = validation_errors


def strip_code_blocks(text: str) -> str:
    """Strip ```json ... ``` code fence markers if present."""
    text = text.strip()
    match = _CODE_BLOCK_RE.match(text)
    if match:
        return match.group(1).strip()
    return text


async def _call_ollama(
    messages: List[Dict[str, str]],
    model: str,
    base_url: str,
    timeout_seconds: float,
    temperature: float,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Execute chat completion against Ollama with format=json."""
    endpoint = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
    }

    try:
        if client is not None:
            response = await client.post(endpoint, json=payload, timeout=timeout_seconds)
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds) as session:
                response = await session.post(endpoint, json=payload)
    except httpx.ConnectError as exc:
        raise LLMCommunicationError(f"Cannot connect to Ollama at '{endpoint}': {exc}") from exc
    except httpx.TimeoutException as exc:
        raise LLMCommunicationError(f"Ollama request timed out after {timeout_seconds}s: {exc}") from exc
    except Exception as exc:
        raise LLMCommunicationError(f"Unexpected error communicating with Ollama: {exc}") from exc

    if response.status_code != 200:
        raise LLMCommunicationError(
            f"Ollama returned HTTP error {response.status_code}: {response.text[:300]}"
        )

    try:
        res_data = response.json()
        return res_data["message"]["content"]
    except Exception as exc:
        raise LLMCommunicationError(f"Failed to parse Ollama response structure: {exc}") from exc


async def _call_openai(
    messages: List[Dict[str, str]],
    model: str,
    api_key: Optional[str],
    temperature: float,
    client: Optional[Any] = None,
) -> str:
    """Execute chat completion against OpenAI with response_format=json_object."""
    try:
        if client is not None:
            oa_client = client
        else:
            from openai import AsyncOpenAI
            if not api_key:
                raise LLMCommunicationError("OpenAI API key not configured or provided.")
            oa_client = AsyncOpenAI(api_key=api_key)

        response = await oa_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        return response.choices[0].message.content or "{}"
    except LLMCommunicationError:
        raise
    except Exception as exc:
        raise LLMCommunicationError(f"OpenAI completion error: {exc}") from exc


async def generate_json(
    prompt: str,
    schema: Type[T],
    system_prompt: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    client: Optional[Any] = None,
    temperature: float = 0.1,
) -> T:
    """Generate and validate a structured JSON object conforming strictly to schema T.

    Args:
        prompt: User prompt / task description.
        schema: Target Pydantic model class.
        system_prompt: Optional system instruction prompt.
        provider: 'ollama', 'openai', or custom registered provider.
        model: Model identifier override.
        base_url: Endpoint base URL override.
        api_key: API key override.
        timeout_seconds: Request timeout override.
        client: Optional pre-configured HTTP/SDK client (useful for mocks and tests).
        temperature: Sampling temperature.

    Returns:
        Validated instance of schema T.

    Raises:
        UnsupportedProviderError: If requested provider is not supported.
        LLMCommunicationError: If provider cannot be reached or returns an HTTP error.
        MalformedJSONError: If LLM output cannot be parsed as JSON.
        SchemaValidationError: If JSON parses but violates Pydantic schema validation.
    """
    settings = get_settings()
    active_provider = (provider or settings.llm_provider or "ollama").strip().lower()

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Execute provider call
    if active_provider == "ollama":
        target_model = model or settings.ollama_model or "qwen2.5:7b"
        target_base_url = base_url or settings.ollama_base_url or "http://localhost:11434"
        target_timeout = timeout_seconds or settings.ollama_timeout_seconds or 300.0
        raw_text = await _call_ollama(
            messages=messages,
            model=target_model,
            base_url=target_base_url,
            timeout_seconds=target_timeout,
            temperature=temperature,
            client=client,
        )
    elif active_provider == "openai":
        target_model = model or settings.llm_model or "gpt-4o-mini"
        target_key = api_key or settings.llm_api_key
        raw_text = await _call_openai(
            messages=messages,
            model=target_model,
            api_key=target_key,
            temperature=temperature,
            client=client,
        )
    else:
        raise UnsupportedProviderError(
            f"Unsupported LLM provider '{active_provider}'. Supported: 'ollama', 'openai'."
        )

    # Parse and validate JSON
    cleaned_text = strip_code_blocks(raw_text)
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse LLM response as JSON: {exc}. Content: {cleaned_text[:200]}")
        raise MalformedJSONError(
            f"LLM output could not be parsed as valid JSON: {exc}",
            raw_output=raw_text,
        ) from exc

    if not isinstance(data, dict):
        raise MalformedJSONError(
            f"Expected JSON object (dict), received {type(data).__name__}",
            raw_output=raw_text,
        )

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        logger.error(f"Structured response failed schema validation: {exc}")
        raise SchemaValidationError(
            f"JSON response failed schema validation for {schema.__name__}: {exc}",
            raw_output=raw_text,
            validation_errors=exc.errors(),
        ) from exc
