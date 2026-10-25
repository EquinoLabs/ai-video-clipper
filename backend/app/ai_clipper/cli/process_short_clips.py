"""Command-line entry point for Stage 3: Standalone Short-Clip Discovery & Rendering."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.ai_clipper.domain.candidates.models import EditorialGoal
from app.core.logging import setup_logging
from app.ai_clipper.services.candidates.short_pipeline import run_short_clip_pipeline

logger = logging.getLogger("app.cli.process_short_clips")


def main():
    parser = argparse.ArgumentParser(
        description="Discover and render short clip moments from an existing long master package (Stage 3)."
    )
    parser.add_argument(
        "long_clip_dir",
        type=Path,
        help="Path to existing long master package directory (e.g. outputs/.../long_clips/clip_01/)",
    )
    parser.add_argument(
        "-o",
        "--run-dir",
        type=Path,
        default=None,
        help="Optional root run directory to save short_clips/ into (defaults to long_clip_dir's run folder)",
    )
    parser.add_argument(
        "-g",
        "--goal",
        type=str,
        default="overall",
        choices=[g.value for g in EditorialGoal],
        help="Editorial goal for short candidate scoring (default: 'overall')",
    )
    parser.add_argument(
        "-i",
        "--instructions",
        type=str,
        default=None,
        help="Custom instructions for short scoring",
    )
    parser.add_argument(
        "-p",
        "--provider",
        type=str,
        default=None,
        choices=["openai", "ollama"],
        help="LLM provider (defaults to settings.llm_provider: 'openai')",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default=None,
        help="Model name (e.g. 'qwen2.5:7b' for ollama or 'gpt-4o-mini' for openai)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="OpenAI API key (or set OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--ollama-base-url",
        type=str,
        default=None,
        help="Ollama base URL (defaults to 'http://localhost:11434')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="LLM request timeout in seconds",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Discover short candidates without rendering video clips",
    )
    parser.add_argument(
        "--render-final",
        action="store_true",
        help="Also render final deliverable (clip_XX_final.mp4 with burned subtitles)",
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

    print("\n" + "=" * 58)
    print("  AI Video Clipper — Standalone Short Discovery (Stage 3)")
    print("=" * 58)
    print(f" Long Master Package : {args.long_clip_dir}")
    print(f" Editorial Goal      : {args.goal}")
    print(f" Render Clean Masters: {not args.no_render}")
    print(f" Render Final Burned : {args.render_final}")
    print("=" * 58 + "\n")

    try:
        res = asyncio.run(
            run_short_clip_pipeline(
                long_clip_dir=args.long_clip_dir,
                output_run_dir=args.run_dir,
                editorial_goal=EditorialGoal(args.goal),
                custom_instructions=args.instructions,
                provider_name=args.provider,
                model_name=args.model,
                api_key=args.api_key,
                ollama_base_url=args.ollama_base_url,
                timeout_seconds=args.timeout,
                render_clean_masters=not args.no_render,
                render_final_deliverables=args.render_final,
            )
        )
        print("\n" + "-" * 58)
        print(" [SUCCESS] Short-Clip Pipeline Complete!")
        print("-" * 58)
        print(f" Parent Long Clip     : {res.long_master_package.metadata.clip_id}")
        print(f" Candidates Discovered: {res.candidates_count}")
        print(f" Short Clips Rendered : {res.rendered_count}")
        print("-" * 58 + "\n")
    except Exception as exc:
        print(f"\n[ERROR] Short-clip pipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
