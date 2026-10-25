"""Service to discover and render long clips (Stage 2) programmatically."""

import json
import logging
from pathlib import Path
from typing import List, Optional

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.ai_clipper.domain.manifest.models import ManifestLongClipItem
from app.ai_clipper.domain.rendering.models import CaptionConfig, FramingConfig, OutputConfig
from app.ai_clipper.domain.transcript.models import TranscriptArtifact
from app.ai_clipper.domain.candidates.models import CandidateArtifact
from app.ai_clipper.cli.discover_candidates import run_candidate_discovery
from app.ai_clipper.services.rendering.long_clip_renderer import render_long_clip_package
from app.ai_clipper.services.storage.output_manager import OutputManager

logger = logging.getLogger(__name__)


async def discover_and_render_long_clips(
    source_video_path: Path,
    transcript_artifact: TranscriptArtifact,
    run_dir: Path,
    source_video_id: str,
    editorial_goal: EditorialGoal = EditorialGoal.OVERALL,
    custom_instructions: Optional[str] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    render_clean_masters: bool = True,
    render_final_deliverables: bool = False,
    framing_config: Optional[FramingConfig] = None,
    caption_config: Optional[CaptionConfig] = None,
    output_config: Optional[OutputConfig] = None,
    output_manager: Optional[OutputManager] = None,
) -> List[ManifestLongClipItem]:
    """Execute Stage 2 long clip discovery and clean master rendering.
    
    Returns list of ManifestLongClipItem for discovered/rendered long clips.
    """
    mgr = output_manager or OutputManager()
    source_video = Path(source_video_path).resolve()

    # Step 1: Ensure transcript artifact exists on disk for discovery service
    transcript_file = run_dir / "transcript.json"
    if not transcript_file.exists():
        mgr.write_json_atomic(transcript_file, transcript_artifact)

    # Step 2: Run long candidate discovery
    logger.info("Executing long-clip candidate discovery...")
    candidates_json_path = await run_candidate_discovery(
        transcript_path=transcript_file,
        output_dir=run_dir,
        editorial_goal=editorial_goal,
        custom_instructions=custom_instructions,
        provider_name=provider_name,
        model_name=model_name,
        mode="long",
    )

    # Step 3: Load discovered candidates
    raw_candidates = json.loads(candidates_json_path.read_text(encoding="utf-8"))
    cand_artifact = CandidateArtifact.model_validate(raw_candidates)

    manifest_long_items: List[ManifestLongClipItem] = []

    # Step 4: Render long clean masters if requested
    if render_clean_masters and cand_artifact.candidates:
        logger.info(f"Rendering clean masters for {len(cand_artifact.candidates)} long candidate(s)...")
        for idx, candidate in enumerate(cand_artifact.candidates, start=1):
            clip_id = f"lng_{idx:03d}"
            try:
                clip_meta, manifest_item = render_long_clip_package(
                    source_video_path=source_video,
                    source_transcript=transcript_artifact,
                    clip_id=clip_id,
                    clip_index=idx,
                    source_start_seconds=candidate.start_seconds,
                    source_end_seconds=candidate.end_seconds,
                    run_dir=run_dir,
                    source_video_id=source_video_id,
                    output_manager=mgr,
                    render_final_deliverable=render_final_deliverables,
                    framing_config=framing_config,
                    caption_config=caption_config,
                    output_config=output_config,
                    hook=candidate.hook,
                    score=float(candidate.overall_score),
                )
                manifest_long_items.append(manifest_item)
            except Exception as e:
                logger.error(f"Failed to render long clip {clip_id}: {e}", exc_info=True)

    return manifest_long_items
