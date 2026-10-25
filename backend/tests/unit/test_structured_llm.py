"""Unit tests for generic structured JSON generator (backend/app/common/llm/structured.py)."""

import json
import pytest
import httpx
from pydantic import BaseModel, Field

from app.common.llm.structured import (
    LLMCommunicationError,
    MalformedJSONError,
    SchemaValidationError,
    UnsupportedProviderError,
    generate_json,
    strip_code_blocks,
)


class SampleSchema(BaseModel):
    name: str = Field(...)
    score: int = Field(...)
    tags: list[str] = Field(default_factory=list)


def test_strip_code_blocks():
    """Verify markdown code block fences are cleanly removed."""
    raw = '```json\n{"name": "test", "score": 90}\n```'
    assert strip_code_blocks(raw) == '{"name": "test", "score": 90}'

    plain = '{"name": "test", "score": 90}'
    assert strip_code_blocks(plain) == plain

    fences_no_lang = '```\n{"name": "test", "score": 90}\n```'
    assert strip_code_blocks(fences_no_lang) == '{"name": "test", "score": 90}'


@pytest.mark.asyncio
async def test_generate_json_success_clean():
    """Verify clean JSON output is parsed into target schema."""
    sample_data = {"name": "Explainer Video", "score": 95, "tags": ["education", "psychology"]}

    # Mock httpx AsyncClient
    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": json.dumps(sample_data)}},
        )
    )
    async with httpx.AsyncClient(transport=handler) as mock_client:
        result = await generate_json(
            prompt="Generate video spec",
            schema=SampleSchema,
            provider="ollama",
            client=mock_client,
        )
        assert isinstance(result, SampleSchema)
        assert result.name == "Explainer Video"
        assert result.score == 95
        assert result.tags == ["education", "psychology"]


@pytest.mark.asyncio
async def test_generate_json_success_with_markdown_fences():
    """Verify LLM output wrapped in ```json ``` markdown code blocks is stripped and parsed."""
    sample_data = {"name": "Wrapped", "score": 88}
    raw_content = f"```json\n{json.dumps(sample_data)}\n```"

    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": raw_content}},
        )
    )
    async with httpx.AsyncClient(transport=handler) as mock_client:
        result = await generate_json(
            prompt="Generate wrapped spec",
            schema=SampleSchema,
            provider="ollama",
            client=mock_client,
        )
        assert result.name == "Wrapped"
        assert result.score == 88


@pytest.mark.asyncio
async def test_generate_json_malformed_json_raises_error():
    """Verify unparseable LLM output raises MalformedJSONError with raw content preserved."""
    raw_bad_json = "Here is the JSON: {name: broken, score: not_a_number}"

    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": raw_bad_json}},
        )
    )
    async with httpx.AsyncClient(transport=handler) as mock_client:
        with pytest.raises(MalformedJSONError) as exc_info:
            await generate_json(
                prompt="Generate spec",
                schema=SampleSchema,
                provider="ollama",
                client=mock_client,
            )
        assert "could not be parsed as valid JSON" in str(exc_info.value)
        assert exc_info.value.raw_output == raw_bad_json


@pytest.mark.asyncio
async def test_generate_json_schema_validation_failure_raises_error():
    """Verify valid JSON missing required schema fields raises SchemaValidationError."""
    invalid_schema_data = {"wrong_key": "No name or score provided"}

    handler = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"message": {"content": json.dumps(invalid_schema_data)}},
        )
    )
    async with httpx.AsyncClient(transport=handler) as mock_client:
        with pytest.raises(SchemaValidationError) as exc_info:
            await generate_json(
                prompt="Generate spec",
                schema=SampleSchema,
                provider="ollama",
                client=mock_client,
            )
        assert "failed schema validation for SampleSchema" in str(exc_info.value)
        assert len(exc_info.value.validation_errors) > 0


@pytest.mark.asyncio
async def test_generate_json_unsupported_provider():
    """Verify passing an unrecognized provider name raises UnsupportedProviderError."""
    with pytest.raises(UnsupportedProviderError) as exc_info:
        await generate_json(
            prompt="Generate",
            schema=SampleSchema,
            provider="unsupported_engine",
        )
    assert "Unsupported LLM provider 'unsupported_engine'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_json_http_error_status_raises_communication_error():
    """Verify HTTP 500 error from provider raises LLMCommunicationError."""
    handler = httpx.MockTransport(
        lambda request: httpx.Response(500, text="Internal Server Error")
    )
    async with httpx.AsyncClient(transport=handler) as mock_client:
        with pytest.raises(LLMCommunicationError) as exc_info:
            await generate_json(
                prompt="Generate",
                schema=SampleSchema,
                provider="ollama",
                client=mock_client,
            )
        assert "Ollama returned HTTP error 500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_json_network_connection_failure():
    """Verify network connection refusal raises LLMCommunicationError."""
    def raise_connect(request):
        raise httpx.ConnectError("Connection refused")

    handler = httpx.MockTransport(raise_connect)
    async with httpx.AsyncClient(transport=handler) as mock_client:
        with pytest.raises(LLMCommunicationError) as exc_info:
            await generate_json(
                prompt="Generate",
                schema=SampleSchema,
                provider="ollama",
                client=mock_client,
            )
        assert "Cannot connect to Ollama" in str(exc_info.value)
