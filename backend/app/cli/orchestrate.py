"""Command-line interface for Stage 4 End-to-End Pipeline Orchestration."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.domain.candidates.models import EditorialGoal
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.pipeline.batch_runner import process_batch_items
from app.services.pipeline.orchestrator import (
    OrchestratorConfig,
    run_pipeline_orchestrator,
)
from app.services.storage.staging import (
    materialize_intake_video,
    resolve_source_videos,
)

logger = logging.getLogger("app.cli.orchestrate")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.orchestrate",
        description="Run end-to-end Stage 4 pipeline orchestration (ingestion, transcription, long clips, short clips)."
    )
    parser.add_argument("source_video", type=str, nargs="?", default=None, help="Path or filename of source video in init_input/")

    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument(
        "--single",
        type=str,
        default=None,
        metavar="VIDEO_SPEC",
        help="Select one specified video from init_input/.",
    )
    mode_group.add_argument(
        "--selected",
        type=str,
        nargs="+",
        default=None,
        metavar="VIDEO_SPEC",
        help="Select a specified list of videos from init_input/.",
    )
    mode_group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Select all eligible videos present in init_input/.",
    )

    parser.add_argument(
        "--source-dir",
        "--init-input",
        type=Path,
        default=Path("init_input"),
        help="Authoritative source library directory (default: init_input/).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Optional specific output directory (defaults to collision-safe run directory in outputs/)",
    )
    parser.add_argument(
        "-t",
        "--transcript",
        type=Path,
        default=None,
        help="Optional path to existing valid transcript.json to reuse without re-transcribing",
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str,
        default="full",
        choices=["full", "long", "short"],
        help="Pipeline orchestration mode (default: full)",
    )
    parser.add_argument(
        "-g",
        "--goal",
        type=str,
        default="overall",
        choices=["overall", "humor", "education", "emotion", "thought_provoking", "hook", "custom"],
        help="Editorial goal for candidate discovery (default: overall)",
    )
    parser.add_argument(
        "-i",
        "--instructions",
        type=str,
        default=None,
        help="Optional custom instructions for discovery",
    )
    parser.add_argument(
        "-p",
        "--provider",
        type=str,
        default=None,
        choices=["openai", "ollama"],
        help="LLM provider (defaults to settings.llm_provider)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model name (defaults to configured model)",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Discover candidates without rendering clean video masters",
    )
    parser.add_argument(
        "--render-final",
        action="store_true",
        help="Also render final deliverable with burned subtitles",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("input"),
        help="Managed date-scoped intake directory (default: input/).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level)

    # Determine selection mode
    if args.selected:
        selection_mode = "selected"
    elif args.all:
        selection_mode = "all"
    elif args.single or args.source_video:
        selection_mode = "single"
    else:
        print("[ERROR] Must specify a source video via positional argument, --single, --selected, or --all.", file=sys.stderr)
        sys.exit(1)

    single_spec = args.single or args.source_video
    source_dir = Path(args.source_dir).resolve()

    # Resolve videos from authoritative init_input library
    try:
        video_files = resolve_source_videos(
            init_input_dir=source_dir,
            mode=selection_mode,
            single=single_spec,
            selected=args.selected,
        )
    except Exception as exc:
        print(f"[ERROR] Source selection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not video_files:
        print(f"\n[INFO] No eligible video files found in '{source_dir}'. Nothing to process.")
        sys.exit(0)

    if len(video_files) > 1 and args.transcript:
        print("[ERROR] Cannot reuse a single transcript for multiple videos.", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    effective_provider = (args.provider or settings.llm_provider or "openai").lower()
    effective_model = (
        args.model or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    config = OrchestratorConfig(
        pipeline_mode=args.mode,
        editorial_goal=EditorialGoal(args.goal),
        custom_instructions=args.instructions,
        llm_provider=effective_provider,
        llm_model=effective_model,
        render_clean_masters=not args.no_render,
        render_final_deliverables=args.render_final,
    )

    # Single video direct orchestration
    if len(video_files) == 1:
        source_target = video_files[0]
        # Materialize into today's intake directory
        staged_res = materialize_intake_video(source_target, input_root=args.input_root)
        if not staged_res.is_staged:
            print(f"[ERROR] Materialization into today's intake failed: {staged_res.error_message}", file=sys.stderr)
            sys.exit(1)

        intake_video_path = staged_res.staged_path

        print("\n" + "=" * 58)
        print("  AI Video Clipper — Stage 4 End-to-End Orchestrator")
        print("=" * 58)
        print(f" Source Video     : {source_target.name}")
        print(f" Materialized Path: {intake_video_path}")
        print(f" Pipeline Mode    : {args.mode}")
        print(f" Editorial Goal   : {args.goal}")
        print(f" Provider         : {effective_provider}")
        print(f" Model            : {effective_model}")
        print(f" Clean Masters    : {not args.no_render}")
        print(f" Final Deliverable: {args.render_final}")
        if args.transcript:
            print(f" Reuse Transcript : {args.transcript}")
        print("=" * 58 + "\n")

        try:
            result = asyncio.run(
                run_pipeline_orchestrator(
                    source_video_path=intake_video_path,
                    config=config,
                    output_dir=args.output_dir,
                    existing_transcript_path=args.transcript,
                )
            )

            print("\n" + "-" * 58)
            print(f" [SUCCESS] Pipeline Orchestration Completed! Status: {result.status.upper()}")
            print("-" * 58)
            print(f" Run ID           : {result.run_id}")
            print(f" Run Directory    : {result.run_dir}")
            print(f" Manifest File    : {result.manifest_path}")
            print(f" Long Clips Count : {result.long_clips_count}")
            print(f" Short Clips Count: {result.short_clips_count}")
            print(f" Elapsed Time     : {result.elapsed_seconds:.2f}s")
            if result.errors:
                print(f" Warnings/Errors  : {len(result.errors)}")
                for err in result.errors:
                    print(f"   - {err}")
            print("-" * 58 + "\n")
            sys.exit(0 if result.status == "completed" else 1)

        except Exception as exc:
            print(f"\n[ERROR] Pipeline orchestration failed: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        # Multiple videos batch execution
        print("\n" + "=" * 58)
        print(f"  AI Video Clipper — Batch Orchestration ({len(video_files)} videos)")
        print("=" * 58)
        summary, exit_code = asyncio.run(
            process_batch_items(
                video_files=video_files,
                config=config,
                input_root=args.input_root,
                existing_transcript_path=args.transcript,
            )
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
