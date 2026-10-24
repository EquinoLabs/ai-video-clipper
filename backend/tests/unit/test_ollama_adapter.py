"""Unit tests for the Ollama local LLM adapter and provider factory."""

import copy
import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.api.v1.schemas.candidates import (
    ConfidenceLabel,
    EditorialGoal,
    GenerationSettings,
)
from app.core.config import Settings
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.candidates.ranking import deduplicate_and_rank_candidates
from app.services.llm.factory import get_llm_provider
from app.services.llm.ollama_adapter import OllamaProvider, OllamaProviderError
from app.services.llm.openai_adapter import OpenAIProvider


def sample_segments():
    return [
        TranscriptSegment(
            id=1,
            start_seconds=10.0,
            end_seconds=25.0,
            duration_seconds=15.0,
            text="In Python, decorators wrap another function in order to extend its behavior.",
            words=[
                WordTiming(word="In", start_seconds=10.0, end_seconds=10.5),
                WordTiming(word="Python,", start_seconds=10.6, end_seconds=11.2),
            ],
        ),
        TranscriptSegment(
            id=2,
            start_seconds=25.0,
            end_seconds=45.0,
            duration_seconds=20.0,
            text="This is useful for logging, authentication, and instrumentation without modifying original code.",
            words=[
                WordTiming(word="This", start_seconds=25.0, end_seconds=25.5),
            ],
        ),
    ]


VALID_CANDIDATE_DATA = {
    "candidates": [
        {
            "start_seconds": 10.0,
            "end_seconds": 45.0,
            "hook": "Understanding Python decorators in 30 seconds",
            "transcript_excerpt": "In Python, decorators wrap another function in order to extend its behavior.",
            "score_dimensions": {
                "hook_strength": 4.5,
                "completeness_coherence": 4.8,
                "standalone_understandability": 4.6,
                "goal_relevance": 5.0,
                "goal_specific_impact": 4.7,
                "specificity_insight": 4.5,
                "pacing_conciseness": 4.2,
                "ending_quality": 4.5,
            },
            "rationale": "Clear self-contained explanation of decorators with concrete use cases.",
            "evidence": [
                {
                    "start_seconds": 10.0,
                    "end_seconds": 25.0,
                    "quote": "In Python, decorators wrap another function in order to extend its behavior.",
                }
            ],
            "confidence_label": "high",
        }
    ]
}


@pytest.mark.asyncio
async def test_ollama_request_construction_and_success():
    """Verify OllamaProvider constructs the correct request payload and parses the envelope."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "model": "qwen2.5:7b",
            "message": {
                "role": "assistant",
                "content": json.dumps(VALID_CANDIDATE_DATA),
            },
            "done": True,
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="qwen2.5:7b",
        timeout_seconds=60.0,
        client=mock_client,
    )

    segments = sample_segments()
    results = await provider.discover_and_evaluate(
        transcript_segments=segments,
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        custom_instructions="Highlight programming fundamentals",
    )

    assert len(results) == 1
    cand = results[0]
    assert cand.hook == "Understanding Python decorators in 30 seconds"
    assert cand.start_seconds == 10.0
    assert cand.end_seconds == 45.0
    assert cand.score_dimensions.goal_relevance == 5.0
    assert cand.confidence_label == ConfidenceLabel.HIGH
    assert len(cand.evidence) == 1

    # Verify request payload details
    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://localhost:11434/api/chat"
    json_body = call_args[1]["json"]
    assert json_body["model"] == "qwen2.5:7b"
    assert json_body["stream"] is False
    assert "format" in json_body
    assert json_body["format"]["type"] == "object"
    assert len(json_body["messages"]) == 2
    assert "EDUCATION" in json_body["messages"][0]["content"]
    assert "Highlight programming fundamentals" in json_body["messages"][1]["content"]


@pytest.mark.asyncio
async def test_ollama_parses_direct_array_response():
    """Verify OllamaProvider normalizes raw JSON array responses without top-level candidates key."""
    raw_array = VALID_CANDIDATE_DATA["candidates"]
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": json.dumps(raw_array),
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
    )

    assert len(results) == 1
    assert results[0].hook == "Understanding Python decorators in 30 seconds"


@pytest.mark.asyncio
async def test_ollama_empty_segments_returns_empty_list():
    """Verify empty segment input returns empty candidate list without invoking network."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    provider = OllamaProvider(client=mock_client)

    results = await provider.discover_and_evaluate(
        transcript_segments=[],
        editorial_goal=EditorialGoal.OVERALL,
        settings=GenerationSettings(),
    )

    assert results == []
    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_ollama_empty_message_content():
    """Verify empty message content from Ollama returns empty candidate list."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": ""}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.OVERALL,
        settings=GenerationSettings(),
    )

    assert results == []


@pytest.mark.asyncio
async def test_ollama_malformed_json_raises_error():
    """Verify unparseable JSON from model raises actionable OllamaProviderError."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": "{ not valid json ...",
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    with pytest.raises(OllamaProviderError, match="Malformed JSON returned by Ollama"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.OVERALL,
            settings=GenerationSettings(),
        )


@pytest.mark.asyncio
async def test_ollama_schema_validation_failure():
    """Verify missing required fields raises schema validation error."""
    bad_data = {"candidates": [{"hook": "No timestamps or dimensions"}]}
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": json.dumps(bad_data),
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    with pytest.raises(OllamaProviderError, match="Ollama model output failed schema validation"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.OVERALL,
            settings=GenerationSettings(),
        )


@pytest.mark.asyncio
async def test_ollama_service_unavailable():
    """Verify connection error produces clear actionable guidance to start Ollama."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    provider = OllamaProvider(base_url="http://localhost:11434", client=mock_client)
    with pytest.raises(OllamaProviderError, match="Ollama service unavailable at 'http://localhost:11434'"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.OVERALL,
            settings=GenerationSettings(),
        )


@pytest.mark.asyncio
async def test_ollama_request_timeout():
    """Verify timeout produces clear actionable timeout message."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("Read timed out")

    provider = OllamaProvider(timeout_seconds=45.0, client=mock_client)
    with pytest.raises(OllamaProviderError, match="timed out after 45.0s"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.OVERALL,
            settings=GenerationSettings(),
        )


@pytest.mark.asyncio
async def test_ollama_missing_model_404():
    """Verify 404 with missing model error instructs user to pull model."""
    mock_response = httpx.Response(
        status_code=404,
        content=json.dumps({"error": "model 'nonexistent:model' not found, try pulling it first"}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(model="nonexistent:model", client=mock_client)
    with pytest.raises(OllamaProviderError, match="Model 'nonexistent:model' not found on Ollama"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.OVERALL,
            settings=GenerationSettings(),
        )


def test_provider_factory_selection():
    """Verify get_llm_provider handles provider selection, defaults, and overrides."""
    # 1. Ollama selection (does not require OpenAI API key)
    ollama_prov = get_llm_provider("ollama")
    assert isinstance(ollama_prov, OllamaProvider)
    assert ollama_prov.model == "qwen2.5:7b"
    assert ollama_prov.base_url == "http://localhost:11434"

    # 2. Ollama with custom model and base_url
    custom_ollama = get_llm_provider(
        provider_name="ollama",
        model_name="llama3.2:3b",
        base_url="http://192.168.1.100:11434/",
    )
    assert isinstance(custom_ollama, OllamaProvider)
    assert custom_ollama.model == "llama3.2:3b"
    assert custom_ollama.base_url == "http://192.168.1.100:11434"

    # 3. OpenAI selection
    openai_prov = get_llm_provider(
        provider_name="openai",
        model_name="gpt-4o",
        api_key="sk-test-key",
    )
    assert isinstance(openai_prov, OpenAIProvider)
    assert openai_prov.model == "gpt-4o"
    assert openai_prov.api_key == "sk-test-key"

    # 4. Invalid provider
    with pytest.raises(ValueError, match="Unsupported LLM provider 'unknown'"):
        get_llm_provider("unknown")


@pytest.mark.asyncio
async def test_backend_scoring_and_ranking_runs_on_ollama_candidates():
    """Verify backend authoritatively calculates overall scores and validates Ollama candidates."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": json.dumps(VALID_CANDIDATE_DATA),
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    segments = sample_segments()
    evaluations = await provider.discover_and_evaluate(
        transcript_segments=segments,
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
    )

    assert len(evaluations) == 1

    # Run authoritative backend deduplication and ranking
    ranking_res = deduplicate_and_rank_candidates(
        evaluations=evaluations,
        segments=segments,
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        source_duration_seconds=60.0,
        iou_threshold=0.50,
    )
    ranked = ranking_res.candidates

    assert len(ranked) == 1
    clip = ranked[0]
    assert clip.id == "cnd_001"
    # Duration authoritatively derived by backend
    assert clip.duration_seconds == 35.0
    # Overall score authoritatively computed by backend (0-100)
    assert 80 <= clip.overall_score <= 100
    assert clip.editorial_goal == EditorialGoal.EDUCATION
    assert clip.evidence[0].quote.startswith("In Python, decorators")


@pytest.mark.asyncio
async def test_ollama_passes_target_count_into_user_prompt():
    """Ollama adapter correctly includes the calculated target_count in prompt sent to Ollama."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": json.dumps(VALID_CANDIDATE_DATA),
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    segments = sample_segments()
    evaluations = await provider.discover_and_evaluate(
        transcript_segments=segments,
        editorial_goal=EditorialGoal.HUMOR,
        settings=GenerationSettings(),
        target_count=4,
    )

    assert len(evaluations) == 1
    # Check payload sent to mock_client
    call_args = mock_client.post.call_args
    sent_payload = call_args.kwargs["json"]
    user_msg = next(m["content"] for m in sent_payload["messages"] if m["role"] == "user")
    assert "Identify approximately 4 distinct, high-potential semantic anchor moments" in user_msg


@pytest.mark.asyncio
async def test_ollama_supports_long_clip_flag():
    """Ollama adapter correctly uses LONG_CLIP_SYSTEM_PROMPT when is_long_clip=True."""
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({
            "message": {
                "role": "assistant",
                "content": json.dumps(VALID_CANDIDATE_DATA),
            }
        }),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    segments = sample_segments()
    evaluations = await provider.discover_and_evaluate(
        transcript_segments=segments,
        editorial_goal=EditorialGoal.HUMOR,
        settings=GenerationSettings.for_long_clips(),
        target_count=3,
        is_long_clip=True,
    )

    assert len(evaluations) == 1
    call_args = mock_client.post.call_args
    sent_payload = call_args.kwargs["json"]
    sys_msg = next(m["content"] for m in sent_payload["messages"] if m["role"] == "system")
    user_msg = next(m["content"] for m in sent_payload["messages"] if m["role"] == "user")
    assert "long-form conversational content curator" in sys_msg
    assert "LONG-CLIP BOUNDARIES & DURATION RULES" in sys_msg
    assert "complete conversational moments and story arcs" in user_msg


# ==============================================================================
# Evidence Recovery and Timestamp Sanitization Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_evidence_recovery_all_valid_candidates_unchanged():
    """Verify that when all candidates and evidence items are valid, behavior is unchanged."""
    raw_payload = copy.deepcopy(VALID_CANDIDATE_DATA)
    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        is_long_clip=True,
    )

    assert len(results) == 1
    assert len(results[0].evidence) == 1
    assert results[0].evidence[0].start_seconds == 10.0
    assert results[0].evidence[0].end_seconds == 25.0


@pytest.mark.asyncio
async def test_evidence_recovery_candidate_with_one_invalid_one_valid_evidence():
    """Verify that an invalid evidence item (end_seconds <= start_seconds) is discarded,

    allowing the candidate to survive with its remaining valid evidence.
    """
    raw_payload = copy.deepcopy(VALID_CANDIDATE_DATA)
    # Add an invalid evidence item (reversed/equal timestamps)
    raw_payload["candidates"][0]["evidence"].append({
        "start_seconds": 347.86,
        "end_seconds": 347.86,
        "quote": "Invalid evidence where end equals start",
    })
    raw_payload["candidates"][0]["evidence"].append({
        "start_seconds": 26.0,
        "end_seconds": 35.0,
        "quote": "Second valid evidence item",
    })

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        is_long_clip=True,
    )

    assert len(results) == 1
    # Invalid evidence item was discarded; 2 valid items survived
    assert len(results[0].evidence) == 2
    assert results[0].evidence[0].start_seconds == 10.0
    assert results[0].evidence[1].start_seconds == 26.0


@pytest.mark.asyncio
async def test_evidence_recovery_candidate_with_only_invalid_evidence_rejected():
    """Verify that a candidate whose only evidence is invalid is rejected with clear diagnostics."""
    raw_payload = copy.deepcopy(VALID_CANDIDATE_DATA)
    raw_payload["candidates"][0]["evidence"] = [
        {
            "start_seconds": 347.86,
            "end_seconds": 340.0,
            "quote": "Reversed timestamps quote",
        }
    ]

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    with pytest.raises(OllamaProviderError, match="leaving no acceptable evidence"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.EDUCATION,
            settings=GenerationSettings(),
            is_long_clip=True,
        )


@pytest.mark.asyncio
async def test_evidence_recovery_invalid_evidence_alongside_other_valid_candidates():
    """Verify that when one candidate has invalid evidence, other valid candidates survive."""
    cand1 = copy.deepcopy(VALID_CANDIDATE_DATA["candidates"][0])
    cand1["hook"] = "Valid Candidate 1"

    cand2 = copy.deepcopy(VALID_CANDIDATE_DATA["candidates"][0])
    cand2["hook"] = "Candidate 2 with only broken evidence"
    cand2["evidence"] = [
        {
            "start_seconds": 150.0,
            "end_seconds": 150.0,
            "quote": "Broken quote equal timestamps",
        }
    ]

    cand3 = copy.deepcopy(VALID_CANDIDATE_DATA["candidates"][0])
    cand3["hook"] = "Valid Candidate 3"

    raw_payload = {"candidates": [cand1, cand2, cand3]}

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        is_long_clip=True,
    )

    # Cand1 and Cand3 survive; Cand2 is rejected
    assert len(results) == 2
    hooks = [r.hook for r in results]
    assert "Valid Candidate 1" in hooks
    assert "Valid Candidate 3" in hooks
    assert "Candidate 2 with only broken evidence" not in hooks


@pytest.mark.asyncio
async def test_evidence_recovery_candidate_level_timestamps_not_repaired():
    """Verify that candidate-level timestamps are not automatically repaired or swapped."""
    raw_payload = copy.deepcopy(VALID_CANDIDATE_DATA)
    # Set candidate-level start > end
    raw_payload["candidates"][0]["start_seconds"] = 45.0
    raw_payload["candidates"][0]["end_seconds"] = 10.0

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    results = await provider.discover_and_evaluate(
        transcript_segments=sample_segments(),
        editorial_goal=EditorialGoal.EDUCATION,
        settings=GenerationSettings(),
        is_long_clip=True,
    )

    assert len(results) == 1
    # Preserves candidate start and end verbatim (not swapped)
    assert results[0].start_seconds == 45.0
    assert results[0].end_seconds == 10.0


@pytest.mark.asyncio
async def test_evidence_recovery_unrelated_malformed_fields_fail_strict_validation():
    """Verify that unrelated malformed required fields still fail strictly."""
    raw_payload = copy.deepcopy(VALID_CANDIDATE_DATA)
    # Delete a required field
    del raw_payload["candidates"][0]["score_dimensions"]

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    with pytest.raises(OllamaProviderError, match="failed schema validation"):
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.EDUCATION,
            settings=GenerationSettings(),
            is_long_clip=True,
        )


@pytest.mark.asyncio
async def test_evidence_recovery_all_candidates_invalid_fails_with_diagnostics():
    """Verify that when all candidates have only invalid evidence, discovery fails clearly with diagnostics."""
    cand1 = copy.deepcopy(VALID_CANDIDATE_DATA["candidates"][0])
    cand1["hook"] = "Bad Candidate 1"
    cand1["evidence"] = [{"start_seconds": 50.0, "end_seconds": 40.0, "quote": "Reversed"}]

    cand2 = copy.deepcopy(VALID_CANDIDATE_DATA["candidates"][0])
    cand2["hook"] = "Bad Candidate 2"
    cand2["evidence"] = [{"start_seconds": 30.0, "end_seconds": 30.0, "quote": "Equal"}]

    raw_payload = {"candidates": [cand1, cand2]}

    mock_response = httpx.Response(
        status_code=200,
        content=json.dumps({"message": {"role": "assistant", "content": json.dumps(raw_payload)}}),
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    provider = OllamaProvider(client=mock_client)
    with pytest.raises(OllamaProviderError) as exc_info:
        await provider.discover_and_evaluate(
            transcript_segments=sample_segments(),
            editorial_goal=EditorialGoal.EDUCATION,
            settings=GenerationSettings(),
            is_long_clip=True,
        )

    err = str(exc_info.value)
    assert "All 2 candidate(s) failed validation" in err
    assert "Bad Candidate 1" in err
    assert "Bad Candidate 2" in err
    assert "leaving no acceptable evidence" in err


def test_evidence_recovery_does_not_mutate_original_parsed_response():
    """Verify that evidence recovery does not mutate the input parsed_raw structure in-place."""
    provider = OllamaProvider()
    original_evidence = [
        {"start_seconds": 10.0, "end_seconds": 20.0, "quote": "Valid"},
        {"start_seconds": 30.0, "end_seconds": 25.0, "quote": "Invalid reversed"},
    ]
    raw_payload = {
        "candidates": [
            {
                **VALID_CANDIDATE_DATA["candidates"][0],
                "evidence": original_evidence,
            }
        ]
    }

    # Execute recovery on payload
    results = provider._sanitize_and_validate_response(parsed_raw=raw_payload, is_long_clip=True)

    # Result has only the 1 valid evidence item
    assert len(results) == 1
    assert len(results[0].evidence) == 1

    # Original payload must remain untouched with both items intact
    assert len(raw_payload["candidates"][0]["evidence"]) == 2
    assert raw_payload["candidates"][0]["evidence"][1]["start_seconds"] == 30.0
    assert raw_payload["candidates"][0]["evidence"][1]["end_seconds"] == 25.0

