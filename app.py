"""Main CLI entry point for AI Video Clipper.

Supports selecting source videos from authoritative init_input/ in three mutually
exclusive modes: single video, selected list of videos, or all videos, then materializing
into the date-scoped input/ YYYY-MM-DD/<source_video_uuid>/ hierarchy before processing.

Usage:
  python app.py --final --single "Anne Hathaway Forgets The Princess Diaries...mp4"
  python app.py --final --single "Anne Hathaway.mp4" -t "outputs/.../transcript.json"
  python app.py --final --selected "clip1.mp4" "clip2.mp4"
  python app.py --final --all
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules are resolvable
project_root = Path(__file__).resolve().parent
backend_dir = project_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.domain.candidates.models import EditorialGoal
from app.services.media.caption_styles import get_caption_style, list_caption_styles
from app.services.pipeline.batch_runner import BatchSummary, process_batch_items
from app.services.pipeline.orchestrator import OrchestratorConfig
from app.services.storage.staging import (
    discover_video_files_in_folder,
    is_supported_video_file,
    resolve_source_videos,
)
from app.core.config import get_settings
from app.core.logging import setup_logging

logger = logging.getLogger("app.main_cli")


def main():
    parser = argparse.ArgumentParser(
        description="AI Video Clipper — Source Selection & Batch Ingestion CLI"
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--single",
        type=str,
        metavar="VIDEO_SPEC",
        help="Select one specified video from init_input/.",
    )
    mode_group.add_argument(
        "--selected",
        type=str,
        nargs="+",
        metavar="VIDEO_SPEC",
        help="Select a specified list of videos from init_input/.",
    )
    mode_group.add_argument(
        "--all",
        nargs="?",
        const=True,
        default=False,
        metavar="FOLDER",
        help="Select all eligible videos present in init_input/ (optional folder override).",
    )

    parser.add_argument(
        "--source-dir",
        "--init-input",
        type=Path,
        default=Path("init_input"),
        help="Authoritative source library directory (default: init_input/).",
    )
    parser.add_argument(
        "-t",
        "--transcript",
        type=Path,
        default=None,
        metavar="TRANSCRIPT_FILE",
        help="Path to an existing valid transcript.json to reuse without re-transcribing (single video only).",
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="Render final burned subtitle deliverables in addition to clean 9:16 vertical masters.",
    )
    available_styles = [s.style_id for s in list_caption_styles()]
    parser.add_argument(
        "--caption-style",
        type=str,
        default="modern-box",
        choices=available_styles,
        help="Caption visual preset style to burn into final deliverables (default: modern-box).",
    )
    parser.add_argument(
        "--goal",
        type=str,
        default="overall",
        choices=["overall", "humor", "education", "emotion", "thought_provoking", "hook", "custom"],
        help="Editorial goal for candidate discovery (default: overall).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["openai", "ollama"],
        help="LLM provider for candidate discovery (defaults to configured provider).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model name (defaults to configured model).",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("input"),
        help="Managed date-scoped intake directory to stage copies into (default: input/).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level.",
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level)

    settings = get_settings()
    effective_provider = (args.provider or settings.llm_provider or "openai").lower()
    effective_model = (
        args.model or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    # Validate batch mode and transcript combination
    if (args.all or args.selected) and args.transcript:
        print(
            "[ERROR] --transcript (-t) cannot be used with --all or multiple videos. "
            "A single transcript cannot be mapped to multiple batch videos.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate transcript file existence if provided
    if args.transcript:
        transcript_path = Path(args.transcript).resolve()
        if not transcript_path.exists():
            print(f"[ERROR] Transcript file not found: {transcript_path}", file=sys.stderr)
            sys.exit(1)
        if not transcript_path.is_file():
            print(f"[ERROR] Transcript path is not a file: {transcript_path}", file=sys.stderr)
            sys.exit(1)

    # 1. Discover target video files strictly from the authoritative source library
    mode = "single" if args.single else ("selected" if args.selected else "all")
    source_dir = Path(args.all) if isinstance(args.all, str) else Path(args.source_dir)

    try:
        video_files = resolve_source_videos(
            init_input_dir=source_dir,
            mode=mode,
            single=args.single,
            selected=args.selected,
        )
    except Exception as exc:
        print(f"[ERROR] Source selection failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not video_files:
        print(f"\n[INFO] Directory '{source_dir}' contains no eligible video files. Nothing to process.")
        sys.exit(0)

    print("\n" + "=" * 60)
    print("  AI Video Clipper — Batch Ingestion & Orchestration Runner")
    print("=" * 60)
    print(f" Selection Mode     : {mode.upper()}")
    print(f" Source Library     : {source_dir}")
    if args.single:
        print(f" Selected Target    : {args.single}")
    elif args.selected:
        print(f" Selected Targets   : {len(args.selected)} file(s)")
    if args.transcript:
        print(f" Reuse Transcript   : {args.transcript}")
    print(f" Resolved Videos    : {len(video_files)}")
    print(f" Final Deliverables : {args.final} (burned subtitles: {args.final})")
    if args.final:
        selected_style = get_caption_style(args.caption_style)
        print(f" Caption Style      : {selected_style.display_name} ({selected_style.style_id})")
    print(f" Editorial Goal     : {args.goal}")
    print(f" LLM Provider       : {effective_provider} ({effective_model})")
    print(f" Intake Directory   : {args.input_root}")
    print("=" * 60 + "\n")

    resolved_caption_preset = get_caption_style(args.caption_style)
    config = OrchestratorConfig(
        pipeline_mode="full",
        editorial_goal=EditorialGoal(args.goal),
        llm_provider=effective_provider,
        llm_model=effective_model,
        render_clean_masters=True,
        render_final_deliverables=args.final,
        caption_config=resolved_caption_preset.config,
    )

    # 2. Execute sequential batch processing with date-scoped materialization
    summary, exit_code = asyncio.run(
        process_batch_items(
            video_files=video_files,
            config=config,
            input_root=args.input_root,
            existing_transcript_path=args.transcript,
        )
    )

    # 3. Print Final Batch Summary
    print("\n" + "=" * 60)
    print("  BATCH EXECUTION SUMMARY")
    print("=" * 60)
    print(f" Batch ID           : {summary.batch_id}")
    print(f" Total Discovered   : {summary.total_discovered_files}")
    print(f" Successfully Done  : {summary.successful_videos}")
    print(f" Failed Videos      : {summary.failed_videos}")
    print(f" Skipped Files      : {summary.skipped_files}")
    print(f" Total Elapsed Time : {summary.total_elapsed_seconds:.2f}s")
    print("-" * 60)

    for idx, item in enumerate(summary.items, start=1):
        status_marker = "[OK]" if item.status == "completed" else ("[SKIP]" if item.status == "skipped" else "[FAIL]")
        print(f" {idx:02d}. {status_marker} {item.original_filename}")
        if item.staged_path:
            print(f"     Materialized: {item.staged_path}")
        if item.run_dir:
            print(f"     Run Folder  : {item.run_dir}")
            print(f"     Clips Ready : {item.long_clips_count} Long(s), {item.short_clips_count} Short(s)")
        if item.error_message:
            print(f"     Error Info  : {item.error_message}")

    print("=" * 60 + "\n")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
