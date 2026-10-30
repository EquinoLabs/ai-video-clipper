"""Unit tests for Caption Styling v1 preset registry, serialization, and proportional scaling."""

from pathlib import Path
import pytest

from app.domain.rendering.models import CaptionConfig, OutputConfig
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.media.caption_styles import (
    DEFAULT_STYLE_ID,
    get_caption_style,
    list_caption_styles,
    resolve_caption_config,
)
from app.services.media.subtitles import (
    build_clip_cues,
    generate_ass_subtitle_content,
    generate_srt_subtitle_content,
)


def test_complete_style_inventory_registration():
    """Verify all 7 AutoShorts styles are registered with correct IDs and display names."""
    styles = list_caption_styles()
    assert len(styles) == 7

    style_ids = [s.style_id for s in styles]
    expected_ids = [
        "modern-box",
        "classic-outline",
        "minimal-shadow",
        "vibrant-cyan",
        "vibrant-yellow-box",
        "vibrant-green",
        "vibrant-red",
    ]
    assert style_ids == expected_ids

    # Verify display names and descriptions
    names = {s.style_id: s.display_name for s in styles}
    assert names["modern-box"] == "Modern Box"
    assert names["classic-outline"] == "Classic Outline"
    assert names["minimal-shadow"] == "Minimal Shadow"
    assert names["vibrant-cyan"] == "Vibrant Cyan"
    assert names["vibrant-yellow-box"] == "Vibrant Yellow Box"
    assert names["vibrant-green"] == "Vibrant Green"
    assert names["vibrant-red"] == "Vibrant Red"

    # Verify preview CSS properties are populated for all styles
    for s in styles:
        assert len(s.preview_css) > 0
        assert "color" in s.preview_css


def test_default_style_and_alias_fallback():
    """Verify default style is modern-box and backward-compatibility aliases resolve cleanly."""
    default_preset = get_caption_style()
    assert default_preset.style_id == DEFAULT_STYLE_ID
    assert default_preset.style_id == "modern-box"

    # Alias checks
    assert get_caption_style("default_bold_v1").style_id == "modern-box"
    assert get_caption_style("modern_box").style_id == "modern-box"
    assert get_caption_style("classic_outline").style_id == "classic-outline"
    assert get_caption_style("vibrant_yellow_box").style_id == "vibrant-yellow-box"

    # Unknown style fallback
    unknown = get_caption_style("non_existent_crazy_style")
    assert unknown.style_id == "modern-box"


def test_style_properties_and_ass_serialization():
    """Verify distinct visual properties serialize into valid ASS styles."""
    cues = [
        type("Cue", (), {"start_seconds": 1.0, "end_seconds": 2.5, "text": "Testing Subtitles"})()
    ]

    # 1. modern-box (BorderStyle=3, opaque box)
    modern_box_cfg = get_caption_style("modern-box").config
    ass_mb = generate_ass_subtitle_content(cues, modern_box_cfg, 1080, 1920)
    assert "PlayResX: 1080" in ass_mb
    assert ",3," in ass_mb  # BorderStyle 3
    assert "TESTING SUBTITLES" in ass_mb  # Uppercase

    # 2. classic-outline (BorderStyle=1, yellow text, thick outline)
    classic_cfg = get_caption_style("classic-outline").config
    ass_co = generate_ass_subtitle_content(cues, classic_cfg, 1080, 1920)
    assert ",1," in ass_co  # BorderStyle 1
    assert "&H0000FFFF" in ass_co  # Yellow PrimaryColour
    assert ",8.0," in ass_co  # Thick outline

    # 3. vibrant-cyan
    cyan_cfg = get_caption_style("vibrant-cyan").config
    ass_vc = generate_ass_subtitle_content(cues, cyan_cfg, 1080, 1920)
    assert "&H00FFFF00" in ass_vc  # Cyan PrimaryColour

    # 4. vibrant-green
    green_cfg = get_caption_style("vibrant-green").config
    ass_vg = generate_ass_subtitle_content(cues, green_cfg, 1080, 1920)
    assert "&H0014FF39" in ass_vg  # Neon green PrimaryColour

    # 5. vibrant-red
    red_cfg = get_caption_style("vibrant-red").config
    ass_vr = generate_ass_subtitle_content(cues, red_cfg, 1080, 1920)
    assert "&H00303BFF" in ass_vr  # Crimson red PrimaryColour


def test_responsive_proportional_width_scaling():
    """Verify font size and box padding scale proportionally to output width.

    Formula: fontsize = clamp(width * 0.075, 16, 80)
    padding = clamp(fontsize * 0.3, 4, 24)
    """
    # At 1080p: width=1080 -> 1080 * 0.075 = 81 -> clamped to 80, padding=24
    cfg_1080 = resolve_caption_config("modern-box", canvas_width=1080)
    assert cfg_1080.font_size == 80

    # At 600p: width=600 -> 600 * 0.075 = 45 -> fontsize=45, padding = 45 * 0.3 = 13.5
    cfg_600 = resolve_caption_config("modern-box", canvas_width=600)
    assert cfg_600.font_size == 45
    assert cfg_600.outline.width == pytest.approx(13.5, 0.1)

    # At 360p: width=360 -> 360 * 0.075 = 27 -> fontsize=27, padding = 27 * 0.3 = 8.1
    cfg_360 = resolve_caption_config("modern-box", canvas_width=360)
    assert cfg_360.font_size == 27
    assert cfg_360.outline.width == pytest.approx(8.1, 0.1)


def test_caption_timing_and_two_word_chunking():
    """Verify 2-word kinetic chunking preserves exact millisecond bounds."""
    segments = [
        TranscriptSegment(
            id=0,
            start_seconds=5.0,
            end_seconds=10.0,
            duration_seconds=5.0,
            text="One two three four five six",
            words=[
                WordTiming(word="One", start_seconds=5.0, end_seconds=5.5),
                WordTiming(word="two", start_seconds=5.5, end_seconds=6.0),
                WordTiming(word="three", start_seconds=6.0, end_seconds=6.8),
                WordTiming(word="four", start_seconds=6.8, end_seconds=7.5),
                WordTiming(word="five", start_seconds=7.5, end_seconds=8.2),
                WordTiming(word="six", start_seconds=8.2, end_seconds=9.0),
            ],
        )
    ]

    cues = build_clip_cues(
        candidate_start_seconds=5.0,
        candidate_end_seconds=10.0,
        transcript_segments=segments,
        max_words_per_cue=2,  # AutoShorts 2-word groups
    )

    assert len(cues) == 3
    assert cues[0].text == "One two"
    assert cues[0].start_seconds == 0.0
    assert cues[0].end_seconds == 1.0

    assert cues[1].text == "three four"
    assert cues[1].start_seconds == 1.0
    assert cues[1].end_seconds == 2.5

    assert cues[2].text == "five six"
    assert cues[2].start_seconds == 2.5
    assert cues[2].end_seconds == 4.0
