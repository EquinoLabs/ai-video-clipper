"""Factory for creating LLM provider instances based on configuration."""

import logging
from typing import Optional

from app.core.config import get_settings
from app.services.llm.base import LLMProvider
from app.services.llm.ollama_adapter import OllamaProvider
from app.services.llm.openai_adapter import OpenAIProvider

logger = logging.getLogger(__name__)


def get_llm_provider(
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    num_predict: Optional[int] = None,
) -> LLMProvider:
    """Instantiate and return the configured LLMProvider.
    
    Supports:
      - 'ollama': Local model (default: qwen2.5:7b, base_url: http://localhost:11434).
      - 'openai': Remote OpenAI model (default: gpt-4o-mini).
    """
    settings = get_settings()
    selected_provider = (provider_name or settings.llm_provider or "openai").strip().lower()

    if selected_provider == "ollama":
        target_model = model_name or settings.ollama_model or "qwen2.5:7b"
        target_base_url = base_url or settings.ollama_base_url or "http://localhost:11434"
        target_timeout = timeout_seconds or settings.ollama_timeout_seconds or 120.0
        target_num_predict = num_predict if num_predict is not None else getattr(settings, "ollama_num_predict", 4096)
        logger.info(f"Instantiating OllamaProvider (model={target_model}, base_url={target_base_url}, num_predict={target_num_predict})")
        return OllamaProvider(
            base_url=target_base_url,
            model=target_model,
            timeout_seconds=target_timeout,
            num_predict=target_num_predict,
        )

    if selected_provider == "openai":
        target_model = model_name or settings.llm_model or "gpt-4o-mini"
        logger.info(f"Instantiating OpenAIProvider (model={target_model})")
        return OpenAIProvider(
            api_key=api_key or settings.llm_api_key,
            model=target_model,
        )

    raise ValueError(
        f"Unsupported LLM provider '{selected_provider}'. Supported options: 'ollama', 'openai'."
    )
