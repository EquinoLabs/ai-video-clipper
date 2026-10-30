"""Candidate discovery and viral scoring service."""

import json
import logging
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.domain.candidates.models import (
    CandidateArtifact,
    CandidateGenerationMetadata,
    EditorialGoal,
    GenerationSettings,
    LLMCandidateEvaluation,
    write_candidate_artifact,
)
from app.domain.transcript.models import TranscriptArtifact
from app.services.candidates.boundaries import refine_candidate_boundaries
from app.services.candidates.ranking import deduplicate_and_rank_candidates
from app.services.candidates.validation import validate_candidate_against_transcript
from app.services.llm.chunking import chunk_transcript
from app.services.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


async def run_candidate_discovery(
    transcript_path: Path,
    output_dir: Optional[Path] = None,
    editorial_goal: EditorialGoal = EditorialGoal.OVERALL,
    custom_instructions: Optional[str] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    ollama_base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    num_predict: Optional[int] = None,
    mode: str = "short",
    candidate_pool_target: Optional[int] = None,
    per_chunk_target: Optional[int] = None,
) -> Path:
    """Run candidate discovery on a transcript artifact and emit candidates.json.

    Supports:
      - mode='short': 10-60s candidate discovery using SYSTEM_PROMPT.
      - mode='long': 30-180s complete conversational arc discovery using LONG_CLIP_SYSTEM_PROMPT
                     and genuine word-timestamp boundary refinement.
    """
    t_path = Path(transcript_path).resolve()
    if not t_path.exists() or not t_path.is_file():
        raise FileNotFoundError(f"Transcript artifact not found: {t_path}")

    # Load transcript artifact
    raw_data = json.loads(t_path.read_text(encoding="utf-8"))
    transcript_artifact = TranscriptArtifact.model_validate(raw_data)

    settings = get_settings()
    is_long_mode = (mode or "short").strip().lower() == "long"

    if is_long_mode:
        effective_pool_target = (
            candidate_pool_target
            if candidate_pool_target is not None
            else settings.long_candidate_pool_target
        )
        effective_display_limit = settings.long_candidate_display_limit
        gen_settings = GenerationSettings.for_long_clips(
            min_duration_seconds=settings.long_clip_min_seconds,
            preferred_min_seconds=settings.long_clip_preferred_min_seconds,
            preferred_max_seconds=settings.long_clip_preferred_max_seconds,
            target_duration_seconds=settings.long_clip_target_seconds,
            max_duration_seconds=settings.long_clip_max_seconds,
            candidate_pool_target=effective_pool_target,
            display_limit=effective_display_limit,
        )
        chunk_size_words = settings.long_transcript_chunk_size
        chunk_overlap_seconds = settings.long_transcript_chunk_overlap_seconds
    else:
        effective_pool_target = (
            candidate_pool_target
            if candidate_pool_target is not None
            else settings.candidate_pool_target
        )
        effective_display_limit = settings.candidate_display_limit
        gen_settings = GenerationSettings(
            min_duration_seconds=settings.clip_min_seconds,
            preferred_min_seconds=settings.clip_preferred_min_seconds,
            preferred_max_seconds=settings.clip_preferred_max_seconds,
            target_duration_seconds=settings.clip_target_seconds,
            max_duration_seconds=settings.clip_max_seconds,
            candidate_pool_target=effective_pool_target,
            display_limit=effective_display_limit,
        )
        chunk_size_words = settings.transcript_chunk_size
        chunk_overlap_seconds = settings.transcript_chunk_overlap_seconds

    out_dir = Path(output_dir).resolve() if output_dir else t_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_output_path = out_dir / "candidates.json"

    effective_provider = (provider_name or settings.llm_provider or "openai").strip().lower()
    effective_model = (
        model_name
        or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    logger.info(f"Loaded transcript artifact: {transcript_artifact.source_media.filename}")
    logger.info(
        f"Mode: {'long' if is_long_mode else 'short'}, Goal: {editorial_goal.value}, Segments: {len(transcript_artifact.segments)}, "
        f"Source duration: {transcript_artifact.source_media.duration_seconds:.2f}s, "
        f"Provider: {effective_provider}, Model: {effective_model}"
    )

    # 1. Chunk transcript
    chunks = chunk_transcript(
        segments=transcript_artifact.segments,
        chunk_size_words=chunk_size_words,
        overlap_seconds=chunk_overlap_seconds,
    )
    logger.info(f"Generated {len(chunks)} transcript chunks for LLM evaluation.")

    # 2. Instantiate LLM provider
    provider = get_llm_provider(
        provider_name=effective_provider,
        model_name=effective_model,
        api_key=api_key or settings.llm_api_key,
        base_url=ollama_base_url or settings.ollama_base_url,
        timeout_seconds=timeout_seconds or settings.ollama_timeout_seconds,
        num_predict=num_predict or getattr(settings, "ollama_num_predict", 4096),
    )

    # 3. Discover candidates across chunks
    all_raw_candidates = []
    num_chunks = len(chunks)
    if per_chunk_target is not None:
        effective_per_chunk_target = max(1, per_chunk_target)
    else:
        effective_per_chunk_target = (
            max(3, -(-gen_settings.candidate_pool_target // num_chunks) + 1)
            if num_chunks > 0
            else 3
        )

    effective_num_predict = num_predict or getattr(settings, "ollama_num_predict", 4096)
    logger.info(
        f"Candidate Discovery Configuration: mode={'long' if is_long_mode else 'short'}, "
        f"total_configured_target={gen_settings.candidate_pool_target}, "
        f"num_chunks={num_chunks}, "
        f"effective_per_chunk_target={effective_per_chunk_target}, "
        f"num_predict={effective_num_predict}"
    )

    failed_chunk_info = None
    chunks_succeeded = 0

    for chunk in chunks:
        logger.info(
            f"Evaluating chunk {chunk.chunk_index + 1}/{chunk.total_chunks} "
            f"([{chunk.start_seconds:.1f}s - {chunk.end_seconds:.1f}s], words={chunk.word_count}, target={effective_per_chunk_target})..."
        )
        try:
            chunk_candidates = await provider.discover_and_evaluate(
                transcript_segments=chunk.segments,
                editorial_goal=editorial_goal,
                settings=gen_settings,
                custom_instructions=custom_instructions,
                target_count=effective_per_chunk_target,
                is_long_clip=is_long_mode,
            )
            all_raw_candidates.extend(chunk_candidates)
            chunks_succeeded += 1
        except Exception as exc:
            logger.error(
                f"Candidate discovery failed on chunk {chunk.chunk_index + 1}/{chunk.total_chunks}: {exc}"
            )
            failed_chunk_info = {
                "chunk_index": chunk.chunk_index,
                "total_chunks": chunk.total_chunks,
                "error": str(exc),
            }
            break

    logger.info(
        f"Gathered {len(all_raw_candidates)} total raw candidate evaluations across {chunks_succeeded}/{num_chunks} chunks."
    )

    # If any chunk failed, preserve completed chunk results if available, then fail clearly
    if failed_chunk_info is not None:
        if all_raw_candidates:
            partial_ranking = deduplicate_and_rank_candidates(
                evaluations=all_raw_candidates,
                segments=transcript_artifact.segments,
                editorial_goal=editorial_goal,
                settings=gen_settings,
                source_duration_seconds=transcript_artifact.source_media.duration_seconds,
                iou_threshold=settings.candidate_iou_threshold,
                is_long_clip=is_long_mode,
            )
            partial_artifact = CandidateArtifact(
                schema_version="v1.0",
                source_media=transcript_artifact.source_media,
                generation=CandidateGenerationMetadata(
                    editorial_goal=editorial_goal,
                    custom_instructions=custom_instructions,
                    provider=effective_provider,
                    model=effective_model,
                    scoring_version="v1.0",
                    settings=gen_settings,
                    chunks_processed=chunks_succeeded,
                    total_raw_candidates=len(all_raw_candidates),
                    rejected_candidates=partial_ranking.rejected_candidates,
                    failed_chunks=[failed_chunk_info],
                ),
                candidates_count=len(partial_ranking.candidates),
                candidates=partial_ranking.candidates,
            )
            partial_path = out_dir / "candidates_partial.json"
            write_candidate_artifact(partial_artifact, partial_path)
            logger.warning(
                f"Preserved {len(partial_ranking.candidates)} partial candidate(s) from {chunks_succeeded} "
                f"successful chunk(s) in {partial_path}"
            )
        fail_msg = (
            f"Candidate discovery failed on chunk {failed_chunk_info['chunk_index'] + 1}/{failed_chunk_info['total_chunks']}: "
            f"{failed_chunk_info['error']}"
        )
        if effective_provider == "ollama":
            from app.services.llm.ollama_adapter import OllamaProviderError
            raise OllamaProviderError(fail_msg)
        raise RuntimeError(fail_msg)

    # 4. Validate, deduplicate, and globally rank candidates
    ranking_result = deduplicate_and_rank_candidates(
        evaluations=all_raw_candidates,
        segments=transcript_artifact.segments,
        editorial_goal=editorial_goal,
        settings=gen_settings,
        source_duration_seconds=transcript_artifact.source_media.duration_seconds,
        iou_threshold=settings.candidate_iou_threshold,
        is_long_clip=is_long_mode,
    )
    ranked_candidates = ranking_result.candidates
    rejected_candidates = ranking_result.rejected_candidates

    # 5. Long-mode word-timestamp boundary refinement & post-refinement validation
    refinement_audits = []
    if is_long_mode and ranked_candidates:
        logger.info("Applying genuine word-timestamp boundary refinement to ranked long candidates...")
        refined_ranked_candidates = []
        for candidate in ranked_candidates:
            ref_res = refine_candidate_boundaries(
                start_seconds=candidate.start_seconds,
                end_seconds=candidate.end_seconds,
                segments=transcript_artifact.segments,
                source_duration_seconds=transcript_artifact.source_media.duration_seconds,
                max_clip_duration_seconds=gen_settings.max_duration_seconds,
            )

            # Revalidate refined candidate against transcript and long duration bounds
            dummy_eval = LLMCandidateEvaluation(
                start_seconds=ref_res.refined_start_seconds,
                end_seconds=ref_res.refined_end_seconds,
                hook=candidate.hook,
                transcript_excerpt=candidate.transcript_excerpt,
                score_dimensions=candidate.score_breakdown,
                rationale=candidate.rationale,
                evidence=candidate.evidence,
                confidence_label=candidate.confidence_label,
            )
            reval_res = validate_candidate_against_transcript(
                candidate=dummy_eval,
                segments=transcript_artifact.segments,
                settings=gen_settings,
                source_duration_seconds=transcript_artifact.source_media.duration_seconds,
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
                "consistency_audit": candidate.consistency_audit,
                "expansion_audit": candidate.expansion_audit,
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
                    f"Refined candidate {candidate.id} failed revalidation: {reval_res.reasons}. "
                    "Reverting to validated pre-refinement interval."
                )
                refined_ranked_candidates.append(candidate)
        ranked_candidates = refined_ranked_candidates

    if rejected_candidates:
        logger.info(
            f"Captured {len(rejected_candidates)} rejected candidate evaluation(s) in diagnostics metadata."
        )

    # 6. Save audit file if refinement occurred
    if refinement_audits:
        refinement_audit_path = out_dir / "boundary_refinement_audit.json"
        refinement_audit_path.write_text(json.dumps(refinement_audits, indent=2), encoding="utf-8")
        logger.info(f"Saved boundary refinement audit: {refinement_audit_path}")

    # 7. Build and write CandidateArtifact
    artifact = CandidateArtifact(
        schema_version="v1.0",
        source_media=transcript_artifact.source_media,
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

    saved_path = write_candidate_artifact(artifact, candidate_output_path)
    logger.info(f"Saved candidate artifact: {saved_path}")
    return saved_path
