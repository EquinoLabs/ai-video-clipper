"""CLI entry point for AI Animation Studio pipeline execution.

Usage:
  python -m app.ai_animation.cli.run_animation --help
"""

import argparse
import sys
from app.ai_animation.config import get_animation_settings


def main():
    parser = argparse.ArgumentParser(
        description="AI Animation Studio — Explainer Video Generation CLI"
    )
    parser.add_argument(
        "--script",
        type=str,
        default=None,
        help="Path to finalized script.json artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Target directory for animation artifacts (defaults to animation_outputs/)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print animation feature configuration and health status",
    )

    args = parser.parse_args()
    settings = get_animation_settings()

    if args.status or len(sys.argv) == 1:
        print("\n" + "=" * 60)
        print(f"  {settings.feature_name} (v{settings.feature_version})")
        print("=" * 60)
        print(f" LLM Provider   : {settings.llm_provider} ({settings.llm_model})")
        print(f" Script Model   : {settings.script_model}")
        print(f" TTS Provider   : {settings.tts_provider} ({settings.default_voice})")
        print(f" Assets Dir     : {settings.assets_dir}")
        print(f" Output Dir     : {settings.output_dir}")
        print(f" Render Canvas  : {settings.render_width}x{settings.render_height} @ {settings.render_fps}fps")
        print("=" * 60 + "\n")
        return

    print(f"Animation feature scaffold ready. Script: {args.script}")


if __name__ == "__main__":
    main()
