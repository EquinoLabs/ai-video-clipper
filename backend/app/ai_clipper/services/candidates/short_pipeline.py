"""Standalone short-clip discovery and extraction pipeline service."""

import json
import logging
from pathlib import Path
from typing import List, NamedTuple, Optional

from app.ai_clipper.domain.candidates.models import EditorialGoal, GenerationSettings
from app.core.config import get_settings
from app.ai_clipper.domain.candidates.models import (
    CandidateArtifact,
    CandidateGenerationMetadata,
    write_candidate_artifact,
)
from app.ai_clipper.domain.manifest.models import ClipMetadata, ManifestShortClipItem, RunManifest
from app.ai_clipper.domain.rendering.models import CaptionConfig, FramingConfig, OutputConfig
from app.ai_clipper.services.candidates.boundaries import refine_candidate_boundaries
from app.ai_clipper.services.candidates.expansion import expand_anchors_to_candidates
from app.ai_clipper.services.candidates.ranking import deduplicate_and_rank_candidates
from app.ai_clipper.services.candidates.short_package import LongMasterPackage, validate_long_master_package
from app.ai_clipper.services.candidates.validation import validate_candidate_against_transcript
from app.ai_clipper.services.llm.base import LLMProvider
from app.ai_clipper.services.llm.chunking import chunk_transcript
from app.ai_clipper.services.llm.factory import get_llm_provider
from app.ai_clipper.services.rendering.short_clip_renderer import render_short_clip_package
from app.ai_clipper.services.storage.output_manager import OutputManager

logger = logging.getLogger(__name__)


class ShortPipelineResult(NamedTuple):
    """Result of running the standalone short-clip pipeline on a long master package."""
    long_master_package: LongMasterPackage
    candidate_artifact: CandidateArtifact
    rendered_shorts: List[ClipMetadata]
    manifest_items: List[ManifestShortClipItem]
    candidates_count: int
    rendered_count: int


async def run_short_clip_pipeline(
    long_clip_dir: Path,
    output_run_dir: Optional[Path] = None,
    editorial_goal: EditorialGoal = EditorialGoal.OVERALL,
    custom_instructions: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    ollama_base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    render_clean_masters: bool = True,
    render_final_deliverables: bool = False,
    framing_config: Optional[FramingConfig] = None,
    caption_config: Optional[CaptionConfig] = None,
    output_config: Optional[OutputConfig] = None,
    output_manager: Optional[OutputManager] = None,
) -> ShortPipelineResult:
    """Execute standalone short-clip discovery and rendering against a long-master package.

    Stages:
    1. Validate long master folder (clean master, transcript.json, metadata.json, clip_type='long').
    2. Load sliced long transcript and reuse word timings without retranscription.
    3. Configure short-mode generation settings (min 10s, target 30s, max 60s).
    4. Chunk long transcript using short chunking parameters if long exceeds chunk size.
    5. Discover candidates with short-mode prompt (is_long_clip=False).
    6. Validate, score, rank, and deduplicate candidates within parent-local bounds.
    7. Refine boundaries with Whisper word timings and revalidate.
    8. Write candidates.json artifact inside the package or target output directory.
    9. If render_clean_masters is True, render clean short masters and update metadata/manifest.
       Valid zero-shorts result is fully permitted.
    """
    settings = get_settings()
    mgr = output_manager or OutputManager()

    # 1. Validate input long-master package
    long_pkg = validate_long_master_package(long_clip_dir)
    long_duration = long_pkg.metadata.timeline.duration_seconds
    long_id = long_pkg.metadata.clip_id

    # Resolve target output run directory (defaults to parent run directory or long_clip_dir.parent.parent)
    run_dir = Path(output_run_dir).resolve() if output_run_dir else long_pkg.package_dir.parent.parent
    short_artifacts_dir = long_pkg.package_dir

    logger.info(
        f"Initiating short-clip pipeline for parent long clip '{long_id}' "
        f"(duration: {long_duration:.2f}s, folder: {long_pkg.package_dir})"
    )

    # 2. Configure short-mode discovery settings
    gen_settings = GenerationSettings.for_short_clips(
        min_duration_seconds=settings.clip_min_seconds,
        preferred_min_seconds=settings.clip_preferred_min_seconds,
        preferred_max_seconds=settings.clip_preferred_max_seconds,
        target_duration_seconds=settings.clip_target_seconds,
        max_duration_seconds=settings.clip_max_seconds,
        candidate_pool_target=settings.candidate_pool_target,
        display_limit=settings.candidate_display_limit,
    )

    # 3. Instantiate LLM provider if not supplied
    if provider is None:
        effective_provider = (provider_name or settings.llm_provider or "openai").strip().lower()
        effective_model = (
            model_name
            or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
        )
        llm_provider = get_llm_provider(
            provider_name=effective_provider,
            model_name=effective_model,
            api_key=api_key or settings.llm_api_key,
            base_url=ollama_base_url or settings.ollama_base_url,
            timeout_seconds=timeout_seconds or settings.ollama_timeout_seconds,
        )
    else:
        llm_provider = provider
        effective_provider = getattr(provider, "name", "custom")
        effective_model = getattr(provider, "model", "custom")

    # 4. Chunk long transcript (reuse sliced segments directly)
    chunks = chunk_transcript(
        segments=long_pkg.transcript.segments,
        chunk_size_words=settings.transcript_chunk_size,
        overlap_seconds=settings.transcript_chunk_overlap_seconds,
    )
    logger.info(f"Generated {len(chunks)} chunk(s) from parent long transcript for short discovery.")

    # 5. Discover short moments across chunks
    all_raw_candidates = []
    expansion_rejected_audits = []
    num_chunks = len(chunks)
    per_chunk_target = (
        max(3, -(-gen_settings.candidate_pool_target // num_chunks) + 1)
        if num_chunks > 0
        else 3
    )

    for chunk in chunks:
        logger.info(
            f"Evaluating short chunk {chunk.chunk_index + 1}/{chunk.total_chunks} "
            f"([{chunk.start_seconds:.1f}s - {chunk.end_seconds:.1f}s], words={chunk.word_count})..."
        )
        chunk_items = await llm_provider.discover_and_evaluate(
            transcript_segments=chunk.segments,
            editorial_goal=editorial_goal,
            settings=gen_settings,
            custom_instructions=custom_instructions,
            target_count=per_chunk_target,
            is_long_clip=False,  # Short-mode prompt
        )
        
        # Check if provider returned semantic anchors (LLMAnchorEvaluation) or candidate evaluations
        if chunk_items and hasattr(chunk_items[0], "anchor_segment_ids"):
            # Bounded window construction from anchors
            expansion_res = expand_anchors_to_candidates(
                anchors=chunk_items,
                chunk_segments=chunk.segments,
                editorial_goal=editorial_goal,
                settings=gen_settings,
                source_duration_seconds=long_duration,
            )
            all_raw_candidates.extend(expansion_res.evaluations)
            expansion_rejected_audits.extend(expansion_res.rejected_audits)
        else:
            all_raw_candidates.extend(chunk_items)

    logger.info(
        f"Gathered {len(all_raw_candidates)} candidate evaluations after anchor-window expansion "
        f"({len(expansion_rejected_audits)} anchor rejections)."
    )

    # 6. Validate, deduplicate, and rank short candidates within long-master container duration
    ranking_result = deduplicate_and_rank_candidates(
        evaluations=all_raw_candidates,
        segments=long_pkg.transcript.segments,
        editorial_goal=editorial_goal,
        settings=gen_settings,
        source_duration_seconds=long_duration,
        iou_threshold=settings.candidate_iou_threshold,
    )
    ranked_candidates = ranking_result.candidates
    # Combine anchor rejection audits with window duration/evidence rejection audits
    rejected_candidates = expansion_rejected_audits + ranking_result.rejected_candidates

    # 7. Word-timestamp boundary refinement & post-refinement validation in long-local coordinates
    refined_ranked_candidates = []
    refinement_audits = []
    if ranked_candidates:
        logger.info("Applying word-timestamp boundary refinement to ranked short candidates...")
        for candidate in ranked_candidates:
            ref_res = refine_candidate_boundaries(
                start_seconds=candidate.start_seconds,
                end_seconds=candidate.end_seconds,
                segments=long_pkg.transcript.segments,
                source_duration_seconds=long_duration,
                max_clip_duration_seconds=gen_settings.max_duration_seconds,
            )

            dummy_eval = candidate.model_copy(
                update={
                    "start_seconds": ref_res.refined_start_seconds,
                    "end_seconds": ref_res.refined_end_seconds,
                }
            )
            reval_res = validate_candidate_against_transcript(
                candidate=dummy_eval,
                segments=long_pkg.transcript.segments,
                settings=gen_settings,
                source_duration_seconds=long_duration,
            )

            audit_item = {
                "candidate_id": candidate.id,
                "raw_interval": [candidate.start_seconds, candidate.end_seconds],
                "refined_interval": [ref_res.refined_start_seconds, ref_res.refined_end_seconds],
                "start_adjusted": ref_res.start_adjusted,
                "end_adjusted": ref_res.end_adjusted,
                "refinement_reason": ref_res.reason,
                "revalidated": reval_res.is_valid,
                "validation_status": reval_res.status.value,
                "validation_reasons": reval_res.reasons,
            }
            refinement_audits.append(audit_item)

            if reval_res.is_valid:
                updated_cand = candidate.model_copy(
                    update={
                        "start_seconds": ref_res.refined_start_seconds,
                        "end_seconds": ref_res.refined_end_seconds,
                        "duration_seconds": ref_res.refined_duration_seconds,
                        "validation_status": reval_res.status,
                    }
                )
                refined_ranked_candidates.append(updated_cand)
            else:
                logger.warning(
                    f"Refined short candidate {candidate.id} failed revalidation: {reval_res.reasons}. "
                    "Reverting to validated pre-refinement interval."
                )
                refined_ranked_candidates.append(candidate)
        ranked_candidates = refined_ranked_candidates

    # 8. Save short candidates artifact
    candidate_artifact = CandidateArtifact(
        schema_version="v1.0",
        source_media=long_pkg.transcript.source_media,
        generation=CandidateGenerationMetadata(
            editorial_goal=editorial_goal,
            custom_instructions=custom_instructions,
            provider=effective_provider,
            model=effective_model,
            scoring_version="v1.0",
            settings=gen_settings,
            chunks_processed=len(chunks),
            total_raw_candidates=len(all_raw_candidates),
            rejected_candidates=rejected_candidates,
        ),
        candidates_count=len(ranked_candidates),
        candidates=ranked_candidates,
    )
    candidates_json_path = short_artifacts_dir / "short_candidates.json"
    write_candidate_artifact(candidate_artifact, candidates_json_path)

    if refinement_audits:
        refinement_audit_path = short_artifacts_dir / "short_boundary_refinement_audit.json"
        refinement_audit_path.write_text(json.dumps(refinement_audits, indent=2), encoding="utf-8")

    # 9. Optional rendering of accepted short clips
    rendered_shorts: List[ClipMetadata] = []
    manifest_items: List[ManifestShortClipItem] = []

    if render_clean_masters and ranked_candidates:
        logger.info(f"Rendering clean short masters for {len(ranked_candidates)} candidate(s)...")
        for idx, cand in enumerate(ranked_candidates, start=1):
            short_clip_id = f"srt_{long_id.split('_')[-1]}_{idx:02d}"
            short_meta, manifest_item = render_short_clip_package(
                parent_clean_master_path=long_pkg.clean_master_path,
                parent_transcript=long_pkg.transcript,
                parent_metadata=long_pkg.metadata,
                clip_id=short_clip_id,
                clip_index=idx,
                parent_local_start_seconds=cand.start_seconds,
                parent_local_end_seconds=cand.end_seconds,
                run_dir=run_dir,
                output_manager=mgr,
                render_final_deliverable=render_final_deliverables,
                framing_config=framing_config,
                caption_config=caption_config,
                output_config=output_config,
                hook=cand.hook,
                score=float(cand.overall_score),
            )
            rendered_shorts.append(short_meta)
            manifest_items.append(manifest_item)

        # Update run manifest if present
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                run_manifest = mgr.load_manifest(run_dir)
                # Append or update short clips in manifest
                existing_short_ids = {s.clip_id for s in run_manifest.short_clips}
                for item in manifest_items:
                    if item.clip_id not in existing_short_ids:
                        run_manifest.short_clips.append(item)
                # Update long clip's short_clips_count
                for lc in run_manifest.long_clips:
                    if lc.clip_id == long_id:
                        lc.short_clips_count = len(manifest_items)
                mgr.save_manifest(run_dir, run_manifest)
                logger.info(f"Updated run manifest with {len(manifest_items)} short clip(s).")
            except Exception as exc:
                logger.warning(f"Could not update run manifest at {manifest_path}: {exc}")

    elif not ranked_candidates:
        logger.info(f"Zero short candidates discovered for long clip '{long_id}'. Zero shorts is a valid result.")

    return ShortPipelineResult(
        long_master_package=long_pkg,
        candidate_artifact=candidate_artifact,
        rendered_shorts=rendered_shorts,
        manifest_items=manifest_items,
        candidates_count=len(ranked_candidates),
        rendered_count=len(rendered_shorts),
    )
