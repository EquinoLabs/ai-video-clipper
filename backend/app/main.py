"""FastAPI main application entrypoint for AI Video Clipper."""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_v1_router
from app.api.v1.schemas.common import ErrorDetail, ErrorResponse
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.common.media.ffmpeg import check_ffmpeg_installed, check_ffprobe_installed

logger = logging.getLogger("ai_video_clipper")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown events."""
    settings = get_settings()
    setup_logging(level=settings.log_level)
    logger.info(f"Starting {settings.app_name} v{settings.app_version} [{settings.environment}]")

    # Diagnostic check for media engine
    ffmpeg_ok, ffmpeg_ver = check_ffmpeg_installed()
    ffprobe_ok, _ = check_ffprobe_installed()
    if ffmpeg_ok and ffprobe_ok:
        logger.info(f"Media engine ready: {ffmpeg_ver}")
    else:
        logger.warning("FFmpeg or FFprobe not found in system PATH. Media processing will be unavailable.")

    yield
    logger.info(f"Shutting down {settings.app_name}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Backend API and processing pipeline for AI Video Clipper",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID Middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    # Standardized Exception Handlers (TechSpec Appendix A)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        errors = exc.errors()
        error_msg = "; ".join(f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in errors)
        payload = ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message=f"Request validation failed: {error_msg}",
                retryable=False,
                request_id=req_id,
            )
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump())

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        payload = ErrorResponse(
            error=ErrorDetail(
                code=f"HTTP_{exc.status_code}",
                message=str(exc.detail),
                retryable=exc.status_code >= 500,
                request_id=req_id,
            )
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error(f"Unhandled exception [req_id={req_id}]: {exc}", exc_info=True)
        payload = ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected internal server error occurred",
                retryable=True,
                request_id=req_id,
            )
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump())

    # Mount API routes
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["root"])
    async def root_index():
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs_url": "/docs",
            "health_url": f"{settings.api_v1_prefix}/health",
        }

    return app


app = create_app()
