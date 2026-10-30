"""Command-line entry point for Phase 3: Candidate Clip Rendering and Validation."""

import argparse
import json
import logging
import sys
from pathlib import Path

from app.core.logging import setup_logging
from app.domain.candidates.models import CandidateArtifact
from app.domain.rendering.models import CaptionConfig, OutputConfig
from app.domain.transcript.models import TranscriptArtifact
from app.services.media.caption_styles import get_caption_style, list_caption_styles
from app.services.media.rendering import render_candidate_clip

logger = logging.getLogger("app.cli.render_clips")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.render_clips",
        description="Render candidate clips to 9:16 vertical MP4 with center crop and synchronized subtitles (Phase 3)."
    )
    parser.add_argument("source_video", type=Path, help="Path to original source video file")
    parser.add_argument(
        "--candidates",
        type=Path,
        required=True,
        help="Path to candidates.json artifact",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Path to transcript.json artifact (for synchronized subtitles)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save rendered MP4 clips (defaults to outputs/rendered_clips/)",
    )
    parser.add_argument(
        "--clip-id",
        type=str,
        default=None,
        help="Specific candidate ID to render (e.g. 'cnd_001'). If omitted, renders all candidates.",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Render video without burning subtitles",
    )
    style_choices = [s.style_id for s in list_caption_styles()]
    parser.add_argument(
        "--caption-style",
        type=str,
        default="modern-box",
        choices=style_choices,
        help="Caption visual preset style to burn into clips (default: modern-box).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level)

    source_path = Path(args.source_video).resolve()
    if not source_path.exists():
        print(f"[ERROR] Source video not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    candidates_path = Path(args.candidates).resolve()
    if not candidates_path.exists():
        print(f"[ERROR] Candidates artifact not found: {candidates_path}", file=sys.stderr)
        sys.exit(1)

    candidate_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    cand_artifact = CandidateArtifact.model_validate(candidate_data)

    transcript_segments = None
    if args.transcript and not args.no_subtitles:
        t_path = Path(args.transcript).resolve()
        if t_path.exists():
            t_data = json.loads(t_path.read_text(encoding="utf-8"))
            t_artifact = TranscriptArtifact.model_validate(t_data)
            transcript_segments = t_artifact.segments

    out_dir = Path(args.output_dir).resolve() if args.output_dir else candidates_path.parent / "rendered_clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 56)
    print("  AI Video Clipper — Candidate Video Renderer (Phase 3)")
    print("=" * 56)
    print(f" Source Video     : {source_path.name}")
    print(f" Candidates File  : {candidates_path.name}")
    print(f" Total Candidates : {len(cand_artifact.candidates)}")
    print(f" Output Directory : {out_dir}")
    print(f" Subtitles        : {'Disabled' if args.no_subtitles else 'Enabled (ASS Burn)'}")
    print("=" * 56 + "\n")

    candidates_to_render = cand_artifact.candidates
    if args.clip_id:
        candidates_to_render = [c for c in cand_artifact.candidates if c.id == args.clip_id]
        if not candidates_to_render:
            print(f"[ERROR] Candidate ID '{args.clip_id}' not found in artifact.", file=sys.stderr)
            sys.exit(1)

    rendered_count = 0
    for cand in candidates_to_render:
        clip_filename = f"{cand.id}_{cand.start_seconds:.1f}s_{cand.end_seconds:.1f}s.mp4"
        out_clip_path = out_dir / clip_filename
        print(f"--> Rendering [{cand.id}]: {cand.hook[:50]}... ({cand.duration_seconds:.1f}s)")

        try:
            caption_preset = get_caption_style(args.caption_style)
            val_res = render_candidate_clip(
                source_video_path=source_path,
                candidate_start_seconds=cand.start_seconds,
                candidate_end_seconds=cand.end_seconds,
                output_mp4_path=out_clip_path,
                transcript_segments=transcript_segments,
                burn_subtitles=not args.no_subtitles,
                caption_config=caption_preset.config,
            )

            if val_res.is_valid:
                print(f"    [SUCCESS] Saved: {out_clip_path.name} ({val_res.width}x{val_res.height}, {val_res.duration_seconds:.2f}s, {val_res.file_size_bytes / (1024*1024):.2f}MB)")
                rendered_count += 1
            else:
                print(f"    [WARNING] Rendered with validation issues: {val_res.validation_errors}")
        except Exception as exc:
            print(f"    [FAILED] Render error: {exc}", file=sys.stderr)

    print("\n" + "-" * 56)
    print(f" Completed: {rendered_count}/{len(candidates_to_render)} clips rendered successfully.")
    print("-" * 56 + "\n")


if __name__ == "__main__":
    main()
