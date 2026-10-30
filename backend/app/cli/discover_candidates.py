"""Command-line entry point for Phase 2: Candidate Discovery and Viral Scoring."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.domain.candidates.models import EditorialGoal
from app.services.candidates.discovery import run_candidate_discovery

__all__ = ["run_candidate_discovery", "main"]

logger = logging.getLogger("app.cli.discover_candidates")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.discover_candidates",
        description="Discover and rank candidate clip moments from a transcript artifact (Phase 2)."
    )
    parser.add_argument("transcript_file", type=Path, help="Path to transcript.json artifact")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="Directory to save candidates.json")
    parser.add_argument(
        "-g",
        "--goal",
        type=str,
        default="overall",
        choices=[g.value for g in EditorialGoal],
        help="Editorial goal for candidate scoring (default: 'overall')",
    )
    parser.add_argument("-i", "--instructions", type=str, default=None, help="Custom instructions for scoring")
    parser.add_argument(
        "-p",
        "--provider",
        type=str,
        default=None,
        choices=["openai", "ollama"],
        help="LLM provider (defaults to settings.llm_provider: 'openai')",
    )
    parser.add_argument("-m", "--model", type=str, default=None, help="Model name (e.g. 'qwen2.5:7b' for ollama or 'gpt-4o-mini' for openai)")
    parser.add_argument("--api-key", type=str, default=None, help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument("--ollama-base-url", type=str, default=None, help="Ollama base URL (defaults to 'http://localhost:11434')")
    parser.add_argument("--timeout", type=float, default=None, help="LLM request timeout in seconds")
    parser.add_argument(
        "--num-predict",
        type=int,
        default=None,
        help="Maximum output tokens for Ollama candidate generation (defaults to settings.ollama_num_predict)",
    )
    parser.add_argument(
        "--candidate-pool-target",
        type=int,
        default=None,
        help="Total candidate pool target across all chunks (defaults to settings.long_candidate_pool_target for long mode, settings.candidate_pool_target for short mode)",
    )
    parser.add_argument(
        "--per-chunk-target",
        type=int,
        default=None,
        help="Direct candidate target requested per transcript chunk (overrides dynamic pool division)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="short",
        choices=["short", "long"],
        help="Discovery mode: 'short' (10-60s) or 'long' (30-180s conversational arcs with boundary refinement)",
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

    settings = get_settings()
    effective_provider = (args.provider or settings.llm_provider or "openai").lower()
    effective_model = (
        args.model
        or (settings.ollama_model if effective_provider == "ollama" else settings.llm_model)
    )

    effective_pool = (
        args.candidate_pool_target
        if args.candidate_pool_target is not None
        else (settings.long_candidate_pool_target if args.mode == "long" else settings.candidate_pool_target)
    )

    print("\n" + "=" * 56)
    print("  AI Video Clipper — Candidate Discovery (Phase 2)")
    print("=" * 56)
    print(f" Mode            : {args.mode}")
    print(f" Transcript File : {args.transcript_file}")
    print(f" Editorial Goal  : {args.goal}")
    print(f" Provider        : {effective_provider}")
    print(f" Model           : {effective_model}")
    print(f" Pool Target     : {effective_pool}")
    if args.per_chunk_target is not None:
        print(f" Per-Chunk Target: {args.per_chunk_target} (manual override)")
    if args.num_predict is not None:
        print(f" Num Predict     : {args.num_predict}")
    if args.instructions:
        print(f" Instructions    : {args.instructions}")
    print("=" * 56 + "\n")

    try:
        saved_file = asyncio.run(
            run_candidate_discovery(
                transcript_path=args.transcript_file,
                output_dir=args.output_dir,
                editorial_goal=EditorialGoal(args.goal),
                custom_instructions=args.instructions,
                provider_name=args.provider,
                model_name=args.model,
                api_key=args.api_key,
                ollama_base_url=args.ollama_base_url,
                timeout_seconds=args.timeout,
                num_predict=args.num_predict,
                mode=args.mode,
                candidate_pool_target=args.candidate_pool_target,
                per_chunk_target=args.per_chunk_target,
            )
        )
        print("\n" + "-" * 56)
        print(" [SUCCESS] Candidate Discovery Complete!")
        print("-" * 56)
        print(f" Candidate Artifact : {saved_file}")
        print("-" * 56 + "\n")
    except Exception as exc:
        print(f"\n[ERROR] Candidate discovery failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
