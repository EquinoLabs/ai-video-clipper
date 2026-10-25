"""API routes for AI Animation Studio.

Mounted under prefix /animation (e.g. /api/v1/animation).
Isolated from clipper review routes.
"""

from fastapi import APIRouter, status
from app.ai_animation.config import get_animation_settings
from app.ai_animation.api.schemas import AnimationConfigResponse, AnimationHealthResponse

router = APIRouter(prefix="/animation", tags=["animation"])


@router.get("/health", response_model=AnimationHealthResponse)
async def get_animation_health():
    """Diagnostic health check for the animation feature."""
    settings = get_animation_settings()
    return AnimationHealthResponse(
        status="ok",
        feature_name=settings.feature_name,
        feature_version=settings.feature_version,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        tts_provider=settings.tts_provider,
    )


@router.get("/config", response_model=AnimationConfigResponse)
async def get_animation_config():
    """Retrieve non-sensitive configuration parameters for animation rendering."""
    settings = get_animation_settings()
    return AnimationConfigResponse(
        feature_name=settings.feature_name,
        feature_version=settings.feature_version,
        render_fps=settings.render_fps,
        render_width=settings.render_width,
        render_height=settings.render_height,
        output_dir=str(settings.output_dir),
        assets_dir=str(settings.assets_dir),
    )
