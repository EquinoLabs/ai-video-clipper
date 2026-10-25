"""API request and response schemas for AI Animation Studio endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnimationHealthResponse(BaseModel):
    status: str = "ok"
    feature_name: str
    feature_version: str
    llm_provider: str
    llm_model: str
    tts_provider: str


class AnimationConfigResponse(BaseModel):
    feature_name: str
    feature_version: str
    render_fps: int
    render_width: int
    render_height: int
    output_dir: str
    assets_dir: str
