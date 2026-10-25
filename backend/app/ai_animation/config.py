"""Configuration settings for AI Animation Studio.

Uses its own environment variable prefix ANIM_ to avoid colliding with
AI Video Clipper settings or core configuration.
"""

from pathlib import Path
from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[3]


class AnimationSettings(BaseSettings):
    """Animation Studio configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="ANIM_",
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application metadata
    feature_name: str = "AI Animation Studio"
    feature_version: str = "0.1.0"
    enabled: bool = True

    # Directories
    output_dir: Path = Field(
        default=Path("animation_outputs"),
        description="Root output directory for animation runs and rendered MP4 scenes",
    )
    assets_dir: Path = Field(
        default_factory=lambda: _REPO_ROOT / "assets" / "ai_animation",
        description="Root directory for character parts, backgrounds, props, and asset manifests",
    )

    # LLM configuration (chosen per step as defined in PRD FR-12)
    llm_provider: str = Field(default="ollama", description="Default provider for scene planning and structured tasks")
    llm_model: str = Field(default="qwen2.5:7b", description="Default model for structured JSON planning")
    script_model: str = Field(default="claude-3-5-sonnet", description="High-tier model for creative scriptwriting")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    ollama_timeout_seconds: float = Field(default=300.0, description="Ollama inference timeout")

    # TTS configuration
    tts_provider: str = Field(default="kokoro", description="TTS synthesis engine (e.g. kokoro, piper, fake)")
    default_voice: str = Field(default="af_bella", description="Default voice model/preset")
    tts_sample_rate: int = Field(default=24000, description="TTS output audio sample rate")

    # Animation and video rendering defaults
    render_fps: int = Field(default=24, description="Target animation frame rate")
    render_width: int = Field(default=1920, description="Canvas horizontal resolution")
    render_height: int = Field(default=1080, description="Canvas vertical resolution")
    max_video_duration_seconds: int = Field(default=1800, description="30 minutes maximum run duration")


@lru_cache()
def get_animation_settings() -> AnimationSettings:
    """Return cached Animation Studio settings instance."""
    return AnimationSettings()
