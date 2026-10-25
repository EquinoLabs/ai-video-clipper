"""Stage 4 Pipeline Orchestrator service.

Coordinates the end-to-end flow:
1. Source probing and isolated run directory allocation.
2. Transcription execution or valid artifact reuse.
3. Long-clip discovery and clean master rendering (Stage 2).
4. Short-clip semantic anchor discovery and clean master rendering on each long master (Stage 3).
5. Comprehensive run manifest generation and validation.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.core.config import get_settings
from app.ai_clipper.domain.manifest.models import (
    ManifestLongClipItem,
    ManifestShortClipItem,
    RunManifest,
    SourceVideoReference,
)
from app.ai_clipper.domain.rendering.models import CaptionConfig, FramingConfig, OutputConfig
from app.ai_clipper.domain.transcript.models import TranscriptArtifact
from app.ai_clipper.services.candidates.short_pipeline import run_short_clip_pipeline
from app.ai_clipper.services.pipeline.long_pipeline import discover_and_render_long_clips
from app.common.media.probing import probe_media_file
from app.ai_clipper.services.pipeline.local_pipeline import run_local_pipeline
from app.ai_clipper.services.storage.output_manager import OutputManager

logger = logging.getLogger(__name__)


class OrchestratorConfig(BaseModel):
    """Configuration options for pipeline orchestration."""
    pipeline_mode: Literal["full", "long", "short"] = "full"
    editorial_goal: EditorialGoal = EditorialGoal.OVERALL
    custom_instructions: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    render_clean_masters: bool = True
    render_final_deliverables: bool = False
    framing_config: Optional[FramingConfig] = None
    caption_config: Optional[CaptionConfig] = None
    output_config: Optional[OutputConfig] = None


class OrchestratorResult(BaseModel):
    """Structured result returned by the pipeline orchestrator."""
    run_id: str
    run_dir: str
    status: Literal["completed", "failed", "partial"]
    manifest_path: str
    source_duration_seconds: float
    long_clips_count: int
    short_clips_count: int
    elapsed_seconds: float
    stage_statuses: Dict[str, str] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


async def run_pipeline_orchestrator(
    source_video_path: Union[str, Path],
    config: Optional[OrchestratorConfig] = None,
    output_dir: Optional[Union[str, Path]] = None,
    existing_transcript_path: Optional[Union[str, Path]] = None,
    output_manager: Optional[OutputManager] = None,
) -> OrchestratorResult:
    """Execute the end-to-end Stage 4 pipeline orchestrator."""
    start_time = time.time()
    cfg = config or OrchestratorConfig()
    mgr = output_manager or OutputManager()
    settings = get_settings()

    source_path = Path(source_video_path).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Source video file not found: {source_path}")

    # Step 1: Probe source video
    logger.info(f"Orchestrator: Probing source media '{source_path.name}'...")
    probe_res = probe_media_file(source_path)
    source_duration = probe_res.duration_seconds

    # Extract or infer canonical video_id and normalized_name
    video_id: str
    safe_stem: str
    metadata_json_candidate = source_path.parent / "metadata.json"
    if metadata_json_candidate.exists():
        try:
            with open(metadata_json_candidate, "r", encoding="utf-8") as f:
                raw_meta = json.load(f)
                video_id = raw_meta.get("video_id") or source_path.parent.name
                original_filename = raw_meta.get("original_filename", "")
                safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in Path(original_filename).stem) if original_filename else source_path.parent.name
        except Exception:
            video_id = source_path.parent.name
            safe_stem = source_path.parent.name
    else:
        safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in source_path.stem)
        video_id = f"vid_{safe_stem}"

    # Determine collision-safe run directory
    if output_dir:
        run_dir = Path(output_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = mgr.create_run_directory(safe_stem)

    run_id = run_dir.name if run_dir.name.startswith("run_") else f"run_{run_dir.name}"

    # Initialize manifest
    manifest = RunManifest(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        pipeline_mode=cfg.pipeline_mode,
        status="running",
        source_video=SourceVideoReference(
            video_id=video_id,
            normalized_name=safe_stem,
            source_path=str(source_path),
            duration_seconds=source_duration,
        ),
        configuration={
            "editorial_goal": cfg.editorial_goal.value,
            "llm_provider": cfg.llm_provider or settings.llm_provider,
            "llm_model": cfg.llm_model or settings.llm_model,
        },
        stage_statuses={
            "transcription": "pending",
            "long_discovery": "pending",
            "short_discovery": "pending",
        },
        long_clips=[],
        short_clips=[],
        errors=[],
    )

    manifest_path = run_dir / "manifest.json"
    mgr.write_json_atomic(manifest_path, manifest)

    stage_statuses = manifest.stage_statuses
    errors = manifest.errors
    transcript_artifact: Optional[TranscriptArtifact] = None

    try:
        # Step 2: Transcription Stage
        stage_statuses["transcription"] = "running"
        transcript_file = run_dir / "transcript.json"

        if existing_transcript_path:
            p = Path(existing_transcript_path).resolve()
            if not p.exists():
                raise FileNotFoundError(f"Provided existing transcript not found: {p}")
            logger.info(f"Orchestrator: Reusing existing transcript from '{p}'")
            raw_t = json.loads(p.read_text(encoding="utf-8"))
            transcript_artifact = TranscriptArtifact.model_validate(raw_t)
            mgr.write_json_atomic(transcript_file, transcript_artifact)
        else:
            logger.info(f"Orchestrator: Running local transcription on '{source_path.name}'...")
            local_res = run_local_pipeline(
                source_file_path=source_path,
                output_dir=run_dir,
                word_timestamps=True,
            )
            transcript_artifact = local_res.artifact

        stage_statuses["transcription"] = "completed"
        mgr.write_json_atomic(manifest_path, manifest)

        # Step 3: Long-Clip Discovery & Rendering (Stage 2)
        rendered_long_packages: List[Path] = []
        if cfg.pipeline_mode in ("full", "long"):
            stage_statuses["long_discovery"] = "running"
            mgr.write_json_atomic(manifest_path, manifest)

            logger.info("Orchestrator: Discovering and rendering Stage 2 long clips...")
            long_items = await discover_and_render_long_clips(
                source_video_path=source_path,
                transcript_artifact=transcript_artifact,
                run_dir=run_dir,
                source_video_id=video_id,
                editorial_goal=cfg.editorial_goal,
                custom_instructions=cfg.custom_instructions,
                provider_name=cfg.llm_provider,
                model_name=cfg.llm_model,
                render_clean_masters=cfg.render_clean_masters,
                render_final_deliverables=cfg.render_final_deliverables,
                framing_config=cfg.framing_config,
                caption_config=cfg.caption_config,
                output_config=cfg.output_config,
                output_manager=mgr,
            )
            manifest.long_clips = long_items
            stage_statuses["long_discovery"] = "completed"
            mgr.write_json_atomic(manifest_path, manifest)

            for item in long_items:
                rendered_long_packages.append(run_dir / item.folder)
        else:
            stage_statuses["long_discovery"] = "skipped"

        # Step 4: Short-Clip Discovery & Rendering (Stage 3)
        if cfg.pipeline_mode in ("full", "short"):
            stage_statuses["short_discovery"] = "running"
            mgr.write_json_atomic(manifest_path, manifest)

            all_short_manifest_items: List[ManifestShortClipItem] = []

            for long_pkg_dir in rendered_long_packages:
                logger.info(f"Orchestrator: Running Stage 3 short discovery on '{long_pkg_dir.name}'...")
                try:
                    short_res = await run_short_clip_pipeline(
                        long_clip_dir=long_pkg_dir,
                        output_run_dir=run_dir,
                        editorial_goal=cfg.editorial_goal,
                        custom_instructions=cfg.custom_instructions,
                        provider_name=cfg.llm_provider,
                        model_name=cfg.llm_model,
                        render_clean_masters=cfg.render_clean_masters,
                        render_final_deliverables=cfg.render_final_deliverables,
                        framing_config=cfg.framing_config,
                        caption_config=cfg.caption_config,
                        output_config=cfg.output_config,
                        output_manager=mgr,
                    )
                    all_short_manifest_items.extend(short_res.manifest_items)
                except Exception as e:
                    err_msg = f"Short discovery failed for long package '{long_pkg_dir.name}': {str(e)}"
                    logger.error(err_msg, exc_info=True)
                    errors.append(err_msg)

            manifest.short_clips = all_short_manifest_items
            stage_statuses["short_discovery"] = "completed"
            mgr.write_json_atomic(manifest_path, manifest)
        else:
            stage_statuses["short_discovery"] = "skipped"

        manifest.status = "completed"
        overall_status: Literal["completed", "partial"] = "completed" if not errors else "partial"

    except Exception as e:
        logger.error(f"Orchestrator failed during execution: {str(e)}", exc_info=True)
        errors.append(str(e))
        manifest.status = "failed"
        overall_status = "failed"
        for stage_name, status in stage_statuses.items():
            if status == "running":
                stage_statuses[stage_name] = "failed"

    # Step 5: Finalize and persist manifest
    manifest.errors = errors
    manifest.stage_statuses = stage_statuses
    mgr.write_json_atomic(manifest_path, manifest)

    elapsed = time.time() - start_time
    return OrchestratorResult(
        run_id=run_id,
        run_dir=str(run_dir),
        status=overall_status,
        manifest_path=str(manifest_path),
        source_duration_seconds=source_duration,
        long_clips_count=len(manifest.long_clips),
        short_clips_count=len(manifest.short_clips),
        elapsed_seconds=round(elapsed, 2),
        stage_statuses=stage_statuses,
        errors=errors,
    )
