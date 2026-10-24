"""Substation Alpha (ASS) and SRT subtitle generator with clip-relative synchronization."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple
from app.domain.rendering.models import CaptionConfig
from app.domain.transcript.models import TranscriptSegment, WordTiming

logger = logging.getLogger(__name__)


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def format_srt_time(seconds: float) -> str:
    """Format seconds into SRT timestamp format: HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def escape_ass_text(text: str) -> str:
    """Escape special characters in text for ASS subtitles."""
    text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return text.strip()


class SubtitleCue:
    def __init__(self, start_seconds: float, end_seconds: float, text: str):
        self.start_seconds = start_seconds
        self.end_seconds = end_seconds
        self.text = text


def build_clip_cues(
    candidate_start_seconds: float,
    candidate_end_seconds: float,
    transcript_segments: List[TranscriptSegment],
    max_words_per_cue: int = 6,
) -> List[SubtitleCue]:
    """Convert absolute transcript segments into clip-relative, chunked subtitle cues.

    Clip-relative time = absolute_time - candidate_start_seconds.
    Clamped strictly to [0.0, candidate_duration].
    """
    clip_duration = round(candidate_end_seconds - candidate_start_seconds, 3)
    cues: List[SubtitleCue] = []

    # Filter segments overlapping [candidate_start_seconds, candidate_end_seconds]
    overlapping_segments = [
        s for s in transcript_segments
        if s.end_seconds > candidate_start_seconds and s.start_seconds < candidate_end_seconds
    ]

    for seg in overlapping_segments:
        # If genuine word timestamps are available, chunk into readable word groups
        if seg.words and len(seg.words) > 0:
            words_in_range = [
                w for w in seg.words
                if w.end_seconds > candidate_start_seconds and w.start_seconds < candidate_end_seconds
            ]
            if not words_in_range:
                continue

            for i in range(0, len(words_in_range), max_words_per_cue):
                group = words_in_range[i : i + max_words_per_cue]
                raw_start = group[0].start_seconds - candidate_start_seconds
                raw_end = group[-1].end_seconds - candidate_start_seconds

                cue_start = max(0.0, min(clip_duration, round(raw_start, 3)))
                cue_end = max(cue_start + 0.1, min(clip_duration, round(raw_end, 3)))
                text = " ".join(w.word for w in group).strip()

                if text and cue_end > cue_start:
                    cues.append(SubtitleCue(start_seconds=cue_start, end_seconds=cue_end, text=text))
        else:
            # Fall back to segment-level timing
            raw_start = seg.start_seconds - candidate_start_seconds
            raw_end = seg.end_seconds - candidate_start_seconds
            cue_start = max(0.0, min(clip_duration, round(raw_start, 3)))
            cue_end = max(cue_start + 0.2, min(clip_duration, round(raw_end, 3)))
            text = seg.text.strip()
            if text and cue_end > cue_start:
                cues.append(SubtitleCue(start_seconds=cue_start, end_seconds=cue_end, text=text))

    return cues


def generate_ass_subtitle_content(
    cues: List[SubtitleCue],
    config: CaptionConfig,
    canvas_width: int = 1080,
    canvas_height: int = 1920,
) -> str:
    """Generate complete ASS subtitle script content with styling and safe margins."""
    margin_v = int(canvas_height * (1.0 - config.position.y))
    margin_h = int(canvas_width * 0.08)  # 8% safe area margin

    # ASS Header
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {canvas_width}",
        f"PlayResY: {canvas_height}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{config.font_family},{config.font_size},{config.text_color},&H0000FFFF,{config.outline.color if config.outline else '&H00000000'},{config.shadow.color if config.shadow else '&H80000000'},"
        f"-1,0,0,0,100,100,0,0,1,{config.outline.width if config.outline else 0},{config.shadow.offset_x if config.shadow else 0},{config.alignment},{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cue in cues:
        start_fmt = format_ass_time(cue.start_seconds)
        end_fmt = format_ass_time(cue.end_seconds)
        clean_text = escape_ass_text(cue.text)
        lines.append(f"Dialogue: 0,{start_fmt},{end_fmt},Default,,0,0,0,,{clean_text}")

    return "\n".join(lines) + "\n"


def generate_srt_subtitle_content(cues: List[SubtitleCue]) -> str:
    """Generate plain SRT subtitle text."""
    blocks = []
    for idx, cue in enumerate(cues, 1):
        start_fmt = format_srt_time(cue.start_seconds)
        end_fmt = format_srt_time(cue.end_seconds)
        blocks.append(f"{idx}\n{start_fmt} --> {end_fmt}\n{cue.text.strip()}\n")
    return "\n".join(blocks)


def write_subtitles_for_candidate(
    candidate_start_seconds: float,
    candidate_end_seconds: float,
    transcript_segments: List[TranscriptSegment],
    output_ass_path: Path,
    output_srt_path: Optional[Path] = None,
    config: Optional[CaptionConfig] = None,
    canvas_width: int = 1080,
    canvas_height: int = 1920,
) -> Path:
    """Generate and write synchronized clip-relative ASS and SRT subtitle files."""
    cfg = config or CaptionConfig()
    cues = build_clip_cues(
        candidate_start_seconds=candidate_start_seconds,
        candidate_end_seconds=candidate_end_seconds,
        transcript_segments=transcript_segments,
        max_words_per_cue=cfg.max_words_per_line,
    )

    ass_content = generate_ass_subtitle_content(
        cues=cues, config=cfg, canvas_width=canvas_width, canvas_height=canvas_height
    )
    Path(output_ass_path).write_text(ass_content, encoding="utf-8")

    if output_srt_path:
        srt_content = generate_srt_subtitle_content(cues)
        Path(output_srt_path).write_text(srt_content, encoding="utf-8")

    return Path(output_ass_path)
