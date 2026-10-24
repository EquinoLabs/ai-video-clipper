"""Batch runner service.

Executes sequential, failure-isolated batch orchestration for single videos
or entire folders of input videos.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field

from app.api.v1.schemas.candidates import EditorialGoal
from app.services.pipeline.orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    run_pipeline_orchestrator,
)
from app.services.storage.output_manager import OutputManager
from app.services.storage.staging import (
    is_supported_video_file,
    stage_input_video,
)

logger = logging.getLogger(__name__)


class VideoBatchItemResult(BaseModel):
    """Result of processing a single video within a batch."""
    source_path: str
    original_filename: str
    staged_path: Optional[str] = None
    status: Literal["completed", "failed", "skipped"]
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    manifest_path: Optional[str] = None
    long_clips_count: int = 0
    short_clips_count: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None


class BatchSummary(BaseModel):
    """Overall summary of a batch run execution."""
    batch_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_discovered_files: int = 0
    successful_videos: int = 0
    failed_videos: int = 0
    skipped_files: int = 0
    total_elapsed_seconds: float = 0.0
    items: List[VideoBatchItemResult] = Field(default_factory=list)


async def process_batch_items(
    video_files: List[Path],
    config: Optional[OrchestratorConfig] = None,
    input_root: Path = Path("input"),
    output_manager: Optional[OutputManager] = None,
    log_dir: Optional[Path] = None,
    existing_transcript_path: Optional[Union[str, Path]] = None,
) -> Tuple[BatchSummary, int]:
    """Process a list of video files sequentially with failure isolation.

    Args:
        video_files: List of video file paths to stage and orchestrate.
        config: Optional pipeline configuration.
        input_root: Managed staging directory.
        output_manager: Output directory and persistence manager.
        log_dir: Batch log directory.
        existing_transcript_path: Optional existing transcript to reuse (single-video only).

    Returns:
        Tuple of (BatchSummary, exit_code).
        Exit code is 0 if all attempted videos succeeded or were cleanly skipped;
        non-zero if any video failed staging or orchestration.
    """
    if existing_transcript_path is not None:
        transcript_p = Path(existing_transcript_path).resolve()
        if not transcript_p.exists():
            raise FileNotFoundError(f"Supplied transcript file not found: {transcript_p}")
        if not transcript_p.is_file():
            raise ValueError(f"Supplied transcript path is not a file: {transcript_p}")
        if len(video_files) > 1:
            raise ValueError(
                "Cannot supply a single transcript for multiple video files in batch mode. "
                "Transcript reuse is only supported for single-video processing."
            )

    start_time = time.time()
    batch_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    batch_id = f"batch_{batch_timestamp}"
    cfg = config or OrchestratorConfig()
    mgr = output_manager or OutputManager()

    summary = BatchSummary(
        batch_id=batch_id,
        total_discovered_files=len(video_files),
    )

    exit_code = 0

    for idx, file_path in enumerate(video_files, start=1):
        item_start = time.time()
        logger.info(f"[{idx}/{len(video_files)}] Processing file: '{file_path.name}'...")

        # 1. Skip non-video files or directories
        if not is_supported_video_file(file_path):
            logger.warning(f"Skipping unsupported file: '{file_path}'")
            summary.skipped_files += 1
            summary.items.append(
                VideoBatchItemResult(
                    source_path=str(file_path),
                    original_filename=file_path.name,
                    status="skipped",
                    error_message=f"Unsupported video format: {file_path.suffix}",
                )
            )
            continue

        # 2. Stage file into input/ directory
        staged_res = stage_input_video(source_file_path=file_path, input_root=input_root)
        if not staged_res.is_staged:
            err = staged_res.error_message or "Staging failed"
            logger.error(f"Staging failed for '{file_path.name}': {err}")
            summary.failed_videos += 1
            exit_code = 1
            summary.items.append(
                VideoBatchItemResult(
                    source_path=str(file_path),
                    original_filename=file_path.name,
                    status="failed",
                    error_message=err,
                    elapsed_seconds=round(time.time() - item_start, 2),
                )
            )
            continue

        # 3. Execute orchestration
        staged_video_path = staged_res.staged_path
        try:
            orch_res: OrchestratorResult = await run_pipeline_orchestrator(
                source_video_path=staged_video_path,
                config=cfg,
                output_manager=mgr,
                existing_transcript_path=existing_transcript_path,
            )

            if orch_res.status == "failed":
                summary.failed_videos += 1
                exit_code = 1
                item_status = "failed"
                err = "; ".join(orch_res.errors) if orch_res.errors else "Orchestration failed"
            else:
                summary.successful_videos += 1
                item_status = "completed"
                err = None

            summary.items.append(
                VideoBatchItemResult(
                    source_path=str(file_path),
                    original_filename=file_path.name,
                    staged_path=str(staged_video_path),
                    status=item_status,
                    run_id=orch_res.run_id,
                    run_dir=orch_res.run_dir,
                    manifest_path=orch_res.manifest_path,
                    long_clips_count=orch_res.long_clips_count,
                    short_clips_count=orch_res.short_clips_count,
                    elapsed_seconds=orch_res.elapsed_seconds,
                    error_message=err,
                )
            )

        except Exception as exc:
            logger.error(f"Unexpected orchestration failure for '{file_path.name}': {exc}", exc_info=True)
            summary.failed_videos += 1
            exit_code = 1
            summary.items.append(
                VideoBatchItemResult(
                    source_path=str(file_path),
                    original_filename=file_path.name,
                    staged_path=str(staged_video_path),
                    status="failed",
                    error_message=str(exc),
                    elapsed_seconds=round(time.time() - item_start, 2),
                )
            )

    summary.total_elapsed_seconds = round(time.time() - start_time, 2)

    # Persist batch summary to disk
    target_log_dir = log_dir or Path("outputs") / "batch_logs"
    target_log_dir.mkdir(parents=True, exist_ok=True)
    summary_path = target_log_dir / f"{batch_id}__summary.json"
    mgr.write_json_atomic(summary_path, summary)
    logger.info(f"Saved batch run summary to: {summary_path}")

    return summary, exit_code
