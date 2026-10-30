"""Command-line entry point for processing a local video file through the media pipeline."""

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.pipeline.local_pipeline import PipelineExecutionError, run_local_pipeline


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.process_local",
        description="Process a local video through the AI Video Clipper media and transcription pipeline.",
    )
    parser.add_argument(
        "source_file",
        type=str,
        help="Path to the input video file (e.g. .mp4, .mov, .mkv, .webm).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Directory to save the transcript artifact and outputs (defaults to outputs/<file>_<timestamp>).",
    )
    parser.add_argument(
        "-m", "--model",
        type=str,
        default=settings.whisper_model,
        help=f"Whisper model size/name (default: '{settings.whisper_model}'). Options: tiny, base, small, medium, large-v3.",
    )
    parser.add_argument(
        "--no-word-timestamps",
        action="store_true",
        help="Disable word-level timestamps (outputs segment timings only).",
    )
    parser.add_argument(
        "-l", "--language",
        type=str,
        default=None,
        help="Language code (e.g. 'en', 'es', 'fr'). Defaults to auto-detection.",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Preserve the extracted 16kHz mono WAV file in the output directory.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=settings.log_level,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    input_path = Path(args.source_file)
    output_dir = Path(args.output_dir) if args.output_dir else None

    print(f"\n========================================================")
    print(f"  AI Video Clipper — Local Pipeline (Phase 1)")
    print(f"========================================================")
    print(f" Source File : {input_path}")
    print(f" Output Dir  : {output_dir or 'Auto-generated in outputs/'}")
    print(f" Whisper Model: {args.model}")
    print(f" Word Timings : {'Disabled' if args.no_word_timestamps else 'Enabled'}")
    print(f" Language     : {args.language or 'Auto-detect'}")
    print(f"========================================================\n")

    try:
        result = run_local_pipeline(
            source_file_path=input_path,
            output_dir=output_dir,
            model_name=args.model,
            word_timestamps=not args.no_word_timestamps,
            language=args.language,
            keep_audio=args.keep_audio,
        )

        print("\n--------------------------------------------------------")
        print(" [SUCCESS] Local Media Pipeline Run Complete!")
        print("--------------------------------------------------------")
        print(f" Output Directory    : {result.output_dir}")
        print(f" Transcript Artifact : {result.transcript_artifact_path}")
        if result.extracted_audio_path:
            print(f" Extracted Audio WAV : {result.extracted_audio_path}")
        print(f" Total Segments      : {result.artifact.segment_count}")
        print(f" Total Words         : {result.artifact.total_words_count}")
        print(f" Detected Language   : {result.artifact.transcription.language} (p={result.artifact.transcription.language_probability})")
        print(f" Word Timestamps     : {'Available' if result.artifact.word_timestamps_available else 'Unavailable'}")
        print(f" Processing Time     : {result.elapsed_seconds:.2f}s")
        print("--------------------------------------------------------\n")
        return 0

    except PipelineExecutionError as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n[FATAL] Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
