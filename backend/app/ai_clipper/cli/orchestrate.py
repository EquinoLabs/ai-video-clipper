"""Command-line interface for Stage 4 End-to-End Pipeline Orchestration."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.ai_clipper.services.pipeline.orchestrator import (
    OrchestratorConfig,
    run_pipeline_orchestrator,
)

logger = logging.getLogger("app.cli.orchestrate")


def main():
    parser = argparse.ArgumentParser(
        description="Run end-to-end Stage 4 pipeline orchestration (ingestion, transcription, long clips, short clips)."
    )
    parser.add_argument("source_video", type=Path, help="Path to source video file")
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
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()
    setup_logging(level=args.log_level)

    source_path = Path(args.source_video).resolve()
    if not source_path.exists():
        print(f"[ERROR] Source video not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    effective_provider = (args.provider or settings.llm_provider or "openai").lower()
    effective_model = (
        args.model or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    print("\n" + "=" * 58)
    print("  AI Video Clipper — Stage 4 End-to-End Orchestrator")
    print("=" * 58)
    print(f" Source Video     : {source_path.name}")
    print(f" Pipeline Mode    : {args.mode}")
    print(f" Editorial Goal   : {args.goal}")
    print(f" Provider         : {effective_provider}")
    print(f" Model            : {effective_model}")
    print(f" Clean Masters    : {not args.no_render}")
    print(f" Final Deliverable: {args.render_final}")
    if args.transcript:
        print(f" Reuse Transcript : {args.transcript}")
    print("=" * 58 + "\n")

    config = OrchestratorConfig(
        pipeline_mode=args.mode,
        editorial_goal=EditorialGoal(args.goal),
        custom_instructions=args.instructions,
        llm_provider=effective_provider,
        llm_model=effective_model,
        render_clean_masters=not args.no_render,
        render_final_deliverables=args.render_final,
    )

    try:
        result = asyncio.run(
            run_pipeline_orchestrator(
                source_video_path=source_path,
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

    except Exception as exc:
        print(f"\n[ERROR] Pipeline orchestration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
