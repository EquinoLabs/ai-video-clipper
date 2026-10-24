"""Local review router for Phase 3 candidate review, video streaming, and downloads."""

import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.api.v1.schemas.review import (
    RenderedClipInfo,
    ReviewCandidateItem,
    ReviewDetailResponse,
    ReviewRunSummary,
)
from app.domain.candidates.models import CandidateArtifact

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])

# Base outputs directory: strictly isolated to <workspace>/outputs
OUTPUTS_BASE_DIR = Path("outputs").resolve()


def _sanitize_path(base_dir: Path, subpath: str) -> Path:
    """Resolve and enforce that the target path stays strictly inside base_dir (path traversal protection)."""
    # Reject null bytes or suspicious characters
    if "\0" in subpath or ".." in subpath:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: path traversal detected.",
        )
    target = (base_dir / subpath).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path is outside the allowed directory.",
        )
    return target


@router.get("/runs", response_model=List[ReviewRunSummary])
async def list_available_runs():
    """List all available processing runs that contain a candidates.json artifact."""
    if not OUTPUTS_BASE_DIR.exists():
        return []

    runs: List[ReviewRunSummary] = []
    for cand_file in OUTPUTS_BASE_DIR.glob("**/candidates.json"):
        run_dir = cand_file.parent
        run_id = run_dir.name

        try:
            raw_data = json.loads(cand_file.read_text(encoding="utf-8"))
            art = CandidateArtifact.model_validate(raw_data)
        except Exception as exc:
            logger.warning(f"Could not parse candidate artifact at {cand_file}: {exc}")
            continue

        rendered_dir = run_dir / "rendered_clips"
        rendered_count = 0
        if rendered_dir.exists():
            for c in art.candidates:
                matches = list(rendered_dir.glob(f"{c.id}_*.mp4"))
                if matches:
                    rendered_count += 1

        runs.append(
            ReviewRunSummary(
                run_id=run_id,
                source_filename=art.source_media.filename,
                source_duration_seconds=art.source_media.duration_seconds,
                editorial_goal=art.generation.editorial_goal,
                created_at=art.created_at,
                total_candidates=len(art.candidates),
                rendered_candidates=rendered_count,
            )
        )

    # Sort newest first
    runs.sort(key=lambda r: r.created_at, reverse=True)
    return runs


@router.get("/runs/{run_id}", response_model=ReviewDetailResponse)
async def get_run_review_details(run_id: str):
    """Get candidate review metadata and media association for a specific run."""
    run_dir = _sanitize_path(OUTPUTS_BASE_DIR, run_id)
    cand_file = run_dir / "candidates.json"

    if not cand_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate artifact not found for run '{run_id}'.",
        )

    try:
        raw_data = json.loads(cand_file.read_text(encoding="utf-8"))
        art = CandidateArtifact.model_validate(raw_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse candidate artifact: {exc}",
        )

    rendered_dir = run_dir / "rendered_clips"
    candidate_items: List[ReviewCandidateItem] = []
    rendered_count = 0

    for c in art.candidates:
        render_info = RenderedClipInfo(is_rendered=False)

        if rendered_dir.exists():
            matches = list(rendered_dir.glob(f"{c.id}_*.mp4"))
            if matches:
                mp4_file = matches[0]
                rendered_count += 1
                base_name = mp4_file.stem
                ass_file = rendered_dir / f"{base_name}.ass"
                srt_file = rendered_dir / f"{base_name}.srt"

                render_info = RenderedClipInfo(
                    is_rendered=True,
                    clip_filename=mp4_file.name,
                    video_url=f"/api/v1/review/runs/{run_id}/media/{mp4_file.name}",
                    download_url=f"/api/v1/review/runs/{run_id}/download/{mp4_file.name}",
                    ass_subtitle_url=f"/api/v1/review/runs/{run_id}/media/{ass_file.name}" if ass_file.exists() else None,
                    srt_subtitle_url=f"/api/v1/review/runs/{run_id}/media/{srt_file.name}" if srt_file.exists() else None,
                    file_size_bytes=mp4_file.stat().st_size,
                    duration_seconds=c.duration_seconds,
                    width=1080,
                    height=1920,
                )

        evidence_quotes = [e.quote for e in c.evidence] if c.evidence else []

        candidate_items.append(
            ReviewCandidateItem(
                id=c.id,
                start_seconds=c.start_seconds,
                end_seconds=c.end_seconds,
                duration_seconds=c.duration_seconds,
                hook=c.hook,
                transcript_excerpt=c.transcript_excerpt,
                editorial_goal=c.editorial_goal,
                overall_score=c.overall_score,
                score_breakdown=c.score_breakdown,
                rationale=c.rationale,
                evidence_quotes=evidence_quotes,
                confidence_label=c.confidence_label.value if hasattr(c.confidence_label, "value") else str(c.confidence_label),
                validation_status=c.validation_status,
                render_info=render_info,
            )
        )

    summary = ReviewRunSummary(
        run_id=run_id,
        source_filename=art.source_media.filename,
        source_duration_seconds=art.source_media.duration_seconds,
        editorial_goal=art.generation.editorial_goal,
        created_at=art.created_at,
        total_candidates=len(art.candidates),
        rendered_candidates=rendered_count,
    )

    return ReviewDetailResponse(summary=summary, candidates=candidate_items)


@router.get("/runs/{run_id}/media/{filename}")
async def serve_media_file(run_id: str, filename: str):
    """Stream rendered clip video or subtitle for browser preview."""
    run_dir = _sanitize_path(OUTPUTS_BASE_DIR, run_id)
    rendered_dir = _sanitize_path(run_dir, "rendered_clips")
    media_file = _sanitize_path(rendered_dir, filename)

    if not media_file.exists() or not media_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media file '{filename}' not found.",
        )

    media_type = "video/mp4" if filename.endswith(".mp4") else "text/plain"
    return FileResponse(path=str(media_file), media_type=media_type)


@router.get("/runs/{run_id}/download/{filename}")
async def download_media_file(run_id: str, filename: str):
    """Download rendered clip as an attachment."""
    run_dir = _sanitize_path(OUTPUTS_BASE_DIR, run_id)
    rendered_dir = _sanitize_path(run_dir, "rendered_clips")
    media_file = _sanitize_path(rendered_dir, filename)

    if not media_file.exists() or not media_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media file '{filename}' not found.",
        )

    return FileResponse(
        path=str(media_file),
        media_type="video/mp4",
        filename=filename,
    )
