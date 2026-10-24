"""Health check endpoint providing runtime and subsystem diagnostic status."""

from fastapi import APIRouter
from app.api.v1.schemas.health import HealthResponse, SubsystemStatus
from app.core.config import get_settings
from app.services.media.ffmpeg import check_ffmpeg_installed, check_ffprobe_installed

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return application health, version, and external provider configuration status."""
    settings = get_settings()

    ffmpeg_ok, ffmpeg_ver = check_ffmpeg_installed()
    ffprobe_ok, ffprobe_ver = check_ffprobe_installed()

    subsystems = {
        "media_engine": SubsystemStatus(
            configured=ffmpeg_ok and ffprobe_ok,
            status="ready" if (ffmpeg_ok and ffprobe_ok) else "missing",
            details=f"ffmpeg: {ffmpeg_ver or 'not found'} | ffprobe: {ffprobe_ver or 'not found'}",
        ),
        "database": SubsystemStatus(
            configured=bool(settings.database_url),
            status="configured" if settings.database_url else "unconfigured",
            details="Neon Postgres connection string configured" if settings.database_url else "Pending configuration",
        ),
        "object_storage": SubsystemStatus(
            configured=bool(settings.r2_bucket_name and settings.r2_access_key_id),
            status="configured" if (settings.r2_bucket_name and settings.r2_access_key_id) else "unconfigured",
            details=f"Cloudflare R2 bucket: {settings.r2_bucket_name or 'Pending configuration'}",
        ),
        "transcription": SubsystemStatus(
            configured=bool(settings.whisper_model),
            status="ready",
            details=f"Whisper model configured: {settings.whisper_model}",
        ),
        "llm": SubsystemStatus(
            configured=bool(settings.llm_api_key),
            status="configured" if settings.llm_api_key else "unconfigured",
            details=f"Provider: {settings.llm_provider} (model: {settings.llm_model})",
        ),
    }

    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version=settings.app_version,
        ffmpeg_available=ffmpeg_ok and ffprobe_ok,
        subsystems=subsystems,
    )
