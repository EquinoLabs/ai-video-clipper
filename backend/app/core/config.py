"""Application configuration management using Pydantic Settings."""

from functools import lru_cache
from typing import List, Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application & Server ---
    app_name: str = "AI Video Clipper"
    app_version: str = "0.2.1"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_v1_prefix: str = "/api/v1"
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]
    app_signing_secret: str = "dev_secret_change_in_production_min_32_characters_long"

    # --- Database (Neon Postgres) ---
    database_url: Optional[str] = None

    # --- Object Storage (Cloudflare R2) ---
    r2_account_id: Optional[str] = None
    r2_bucket_name: Optional[str] = None
    r2_access_key_id: Optional[str] = None
    r2_secret_access_key: Optional[str] = None
    r2_endpoint_url: Optional[str] = None

    # --- Media & Processing Limits ---
    max_upload_bytes: int = Field(default=1024 * 1024 * 1024, description="1 GB limit")
    max_source_duration_seconds: int = Field(default=7200, description="2 hours limit")
    temp_disk_budget_bytes: int = Field(default=20 * 1024 * 1024 * 1024, description="20 GB")
    job_timeout_seconds: int = 3600
    worker_concurrency: int = 1
    source_retention_policy: str = "retain_until_user_deletes_or_outputs_verified"

    # --- Clip Generation Defaults (Configurable) ---
    clip_min_seconds: float = 10.0
    clip_preferred_min_seconds: float = 15.0
    clip_preferred_max_seconds: float = 45.0
    clip_target_seconds: float = 30.0
    clip_max_seconds: float = 60.0
    candidate_pool_target: int = 10
    candidate_display_limit: int = 10

    # --- Long Clip Generation Defaults (Stage 2) ---
    long_clip_min_seconds: float = 30.0
    long_clip_preferred_min_seconds: float = 45.0
    long_clip_preferred_max_seconds: float = 120.0
    long_clip_target_seconds: float = 90.0
    long_clip_max_seconds: float = 180.0
    long_candidate_pool_target: int = 10
    long_candidate_display_limit: int = 10
    long_transcript_chunk_size: int = 1500
    long_transcript_chunk_overlap_seconds: float = 60.0

    # --- Transcription (Whisper) ---
    whisper_model: str = "base"

    # --- LLM Provider & Evaluation ---
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: Optional[str] = None
    transcript_chunk_size: int = 750
    transcript_chunk_overlap_seconds: float = 45.0
    candidate_iou_threshold: float = 0.50

    # --- Ollama Local LLM Settings ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 300.0

    # --- Visual Analysis (Phased) ---
    visual_frame_sample_interval_seconds: float = 2.0


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
