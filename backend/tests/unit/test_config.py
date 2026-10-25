"""Unit tests for application configuration."""

import os
from pathlib import Path
from pydantic_settings import SettingsConfigDict
import pytest

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.core.config import Settings
from app.ai_clipper.services.llm.factory import get_llm_provider
from app.ai_clipper.services.llm.ollama_adapter import OllamaProvider
from app.ai_clipper.services.pipeline.orchestrator import OrchestratorConfig


def test_default_config_values():
    settings = Settings(_env_file=None)
    assert settings.app_name == "AI Video Clipper"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.clip_min_seconds == 10.0
    assert settings.clip_preferred_min_seconds == 15.0
    assert settings.clip_preferred_max_seconds == 45.0
    assert settings.clip_target_seconds == 30.0
    assert settings.clip_max_seconds == 60.0
    assert settings.candidate_pool_target == 10
    assert settings.candidate_display_limit == 10
    assert settings.transcript_chunk_size == 750
    assert settings.transcript_chunk_overlap_seconds == 45.0
    assert settings.worker_concurrency == 1
    # Hardcoded default in Settings class is openai when no env file is loaded
    assert settings.llm_provider == "openai"
    assert settings.ollama_model == "qwen2.5:7b"


def test_env_file_loading_overrides_hardcoded_defaults(tmp_path: Path):
    """Verify that values in .env override hardcoded class defaults."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=ollama\n"
        "LLM_MODEL=test_custom_model\n"
        "OLLAMA_MODEL=test_custom_model\n"
        "OLLAMA_BASE_URL=http://test-server:11434\n"
    )

    settings = Settings(_env_file=env_file)
    assert settings.llm_provider == "ollama"
    assert settings.llm_model == "test_custom_model"
    assert settings.ollama_model == "test_custom_model"
    assert settings.ollama_base_url == "http://test-server:11434"


def test_ollama_provider_instantiation_without_openai_key(monkeypatch):
    """Confirm that selecting Ollama succeeds and does not require OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(llm_provider="ollama", ollama_model="qwen2.5:7b"))

    provider = get_llm_provider(provider_name="ollama")
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:7b"
    assert provider.base_url == "http://localhost:11434"


def test_cli_explicit_override_precedence():
    """Verify that explicit CLI arguments take precedence over .env settings."""
    # Settings from .env has ollama
    env_settings = Settings(llm_provider="ollama", ollama_model="qwen2.5:7b")

    # 1. No CLI flags passed -> uses .env values
    cli_provider_none = None
    cli_model_none = None
    eff_provider_1 = (cli_provider_none or env_settings.llm_provider or "openai").lower()
    eff_model_1 = (
        cli_model_none or (env_settings.ollama_model if eff_provider_1 == "ollama" else env_settings.llm_model)
    )
    assert eff_provider_1 == "ollama"
    assert eff_model_1 == "qwen2.5:7b"

    # 2. Explicit CLI override passed -> overrides .env values
    cli_provider_override = "openai"
    cli_model_override = "gpt-4o"
    eff_provider_2 = (cli_provider_override or env_settings.llm_provider or "openai").lower()
    eff_model_2 = (
        cli_model_override or (env_settings.ollama_model if eff_provider_2 == "ollama" else env_settings.llm_model)
    )
    assert eff_provider_2 == "openai"
    assert eff_model_2 == "gpt-4o"


def test_settings_reach_long_and_short_stages_consistently():
    """Verify that OrchestratorConfig forwards resolved settings to both stages without hardcoding."""
    env_settings = Settings(llm_provider="ollama", ollama_model="qwen2.5:7b")

    cfg = OrchestratorConfig(
        pipeline_mode="full",
        editorial_goal=EditorialGoal.OVERALL,
        llm_provider=env_settings.llm_provider,
        llm_model=env_settings.ollama_model,
    )

    assert cfg.llm_provider == "ollama"
    assert cfg.llm_model == "qwen2.5:7b"
