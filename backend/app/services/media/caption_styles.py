"""Caption styling presets and configuration based on AutoShorts reverse engineering findings.

Provides 7 distinct, configuration-driven caption presets with full ASS and SRT serialization,
proportional responsive scaling, and safe fallback behavior.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.domain.rendering.models import CaptionConfig, CaptionOutline, CaptionPosition, CaptionShadow


class CaptionStylePreset(BaseModel):
    """Definition and metadata for a registered caption style preset."""

    style_id: str = Field(..., description="Unique machine identifier for style (e.g. 'modern-box')")
    display_name: str = Field(..., description="Human-readable name for UI and logs")
    description: str = Field(..., description="Detailed visual description and inspiration")
    sample_text: str = Field(default="VIRAL CLIPS", description="Sample text for UI previews")
    config: CaptionConfig = Field(..., description="Underlying CaptionConfig for rendering")
    preview_css: Dict[str, str] = Field(
        default_factory=dict,
        description="Lightweight CSS properties for rendering a 1:1 fidelity browser preview",
    )


# The 7 AutoShorts Visual Caption Styles (with default-bold-v1 backward compatibility alias)
PRESET_MODERN_BOX = CaptionStylePreset(
    style_id="modern-box",
    display_name="Modern Box",
    description="Crisp white text inside a semi-transparent dark rounded box (AutoShorts Default)",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="modern-box",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H00FFFFFF",  # Opaque white
        highlight_color="&H0000FFFF",
        border_style=3,  # ASS Opaque Box
        box_color="&H50000000",  # Dark box (~70% opacity in ASS alpha: &H50 = 80/255 transparency)
        outline=CaptionOutline(color="&H50000000", width=14.0),  # Box padding in BorderStyle=3
        shadow=CaptionShadow(color="&H00000000", offset_x=0.0, offset_y=0.0),
        alignment=2,  # Bottom center
        position=CaptionPosition(x=0.5, y=0.72),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#ffffff",
        "backgroundColor": "rgba(0, 0, 0, 0.70)",
        "padding": "4px 10px",
        "borderRadius": "6px",
        "fontWeight": "800",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_CLASSIC_OUTLINE = CaptionStylePreset(
    style_id="classic-outline",
    display_name="Classic Outline",
    description="Bright yellow text with thick black border (CapCut social media aesthetic)",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="classic-outline",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H0000FFFF",  # Bright Yellow in ASS (&H00BBGGRR -> Red=00, Green=FF, Blue=FF)
        highlight_color="&H00FFFFFF",
        border_style=1,  # Outline + Shadow
        outline=CaptionOutline(color="&H00000000", width=8.0),  # Thick black border (fontsize * 0.1)
        shadow=CaptionShadow(color="&H00000000", offset_x=2.0, offset_y=2.0),
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.65),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#ffff00",
        "WebkitTextStroke": "2px #000000",
        "textShadow": "2px 2px 0px #000000",
        "fontWeight": "900",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_MINIMAL_SHADOW = CaptionStylePreset(
    style_id="minimal-shadow",
    display_name="Minimal Shadow",
    description="Clean white text with subtle black drop shadow for restrained elegance",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="minimal-shadow",
        font_family="Arial",
        font_size=76,
        font_weight="Bold",
        text_color="&H00FFFFFF",  # Pure white
        highlight_color="&H0000FFFF",
        border_style=1,
        outline=CaptionOutline(color="&H00000000", width=1.5),  # Thin crisp stroke
        shadow=CaptionShadow(color="&H80000000", offset_x=3.0, offset_y=3.0),  # Subtle black shadow
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.70),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#ffffff",
        "textShadow": "2px 2px 4px rgba(0, 0, 0, 0.75)",
        "fontWeight": "800",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_VIBRANT_CYAN = CaptionStylePreset(
    style_id="vibrant-cyan",
    display_name="Vibrant Cyan",
    description="Electric cyber-cyan text (#00FFFF) with deep black drop shadow",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="vibrant-cyan",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H00FFFF00",  # Cyan in ASS (&H00BBGGRR -> Blue=FF, Green=FF, Red=00)
        highlight_color="&H00FFFFFF",
        border_style=1,
        outline=CaptionOutline(color="&H00000000", width=3.0),
        shadow=CaptionShadow(color="&H66000000", offset_x=3.0, offset_y=3.0),
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.70),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#00ffff",
        "WebkitTextStroke": "1px #000000",
        "textShadow": "3px 3px 6px rgba(0, 0, 0, 0.8)",
        "fontWeight": "800",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_VIBRANT_YELLOW_BOX = CaptionStylePreset(
    style_id="vibrant-yellow-box",
    display_name="Vibrant Yellow Box",
    description="High-contrast black text inside an opaque canary yellow box (TikTok style)",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="vibrant-yellow-box",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H00000000",  # Opaque black text
        highlight_color="&H00FFFFFF",
        border_style=3,  # Opaque box
        box_color="&H0000FFFF",  # Canary yellow in ASS (&H00BBGGRR -> Red=00, Green=FF, Blue=FF)
        outline=CaptionOutline(color="&H0000FFFF", width=14.0),  # Yellow box padding
        shadow=CaptionShadow(color="&H00000000", offset_x=0.0, offset_y=0.0),
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.72),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#000000",
        "backgroundColor": "#ffff00",
        "padding": "4px 10px",
        "borderRadius": "4px",
        "fontWeight": "900",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_VIBRANT_GREEN = CaptionStylePreset(
    style_id="vibrant-green",
    display_name="Vibrant Green",
    description="Neon green text (#39FF14) with black outline and shadow (Alex Hormozi style)",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="vibrant-green",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H0014FF39",  # Neon green in ASS (&H00BBGGRR: Red=39, Green=FF, Blue=14)
        highlight_color="&H00FFFFFF",
        border_style=1,
        outline=CaptionOutline(color="&H00000000", width=6.5),  # fontsize * 0.08 outline
        shadow=CaptionShadow(color="&H66000000", offset_x=2.5, offset_y=2.5),
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.70),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#39ff14",
        "WebkitTextStroke": "2px #000000",
        "textShadow": "2px 2px 4px #000000",
        "fontWeight": "900",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

PRESET_VIBRANT_RED = CaptionStylePreset(
    style_id="vibrant-red",
    display_name="Vibrant Red",
    description="Crimson red text (#FF3B30) with bold outline and shadow (High Energy/Drama)",
    sample_text="VIRAL CLIPS",
    config=CaptionConfig(
        preset_id="vibrant-red",
        font_family="Arial",
        font_size=80,
        font_weight="Bold",
        text_color="&H00303BFF",  # Crimson red in ASS (&H00BBGGRR: Red=FF, Green=3B, Blue=30)
        highlight_color="&H00FFFFFF",
        border_style=1,
        outline=CaptionOutline(color="&H00000000", width=6.5),  # fontsize * 0.08 outline
        shadow=CaptionShadow(color="&H66000000", offset_x=2.5, offset_y=2.5),
        alignment=2,
        position=CaptionPosition(x=0.5, y=0.70),
        max_words_per_line=2,
        max_lines_per_cue=1,
        timing_mode="word",
        uppercase=True,
    ),
    preview_css={
        "color": "#ff3b30",
        "WebkitTextStroke": "2px #000000",
        "textShadow": "2px 2px 4px #000000",
        "fontWeight": "900",
        "textTransform": "uppercase",
        "letterSpacing": "0.05em",
    },
)

# Registry dictionary
_STYLE_REGISTRY: Dict[str, CaptionStylePreset] = {
    PRESET_MODERN_BOX.style_id: PRESET_MODERN_BOX,
    PRESET_CLASSIC_OUTLINE.style_id: PRESET_CLASSIC_OUTLINE,
    PRESET_MINIMAL_SHADOW.style_id: PRESET_MINIMAL_SHADOW,
    PRESET_VIBRANT_CYAN.style_id: PRESET_VIBRANT_CYAN,
    PRESET_VIBRANT_YELLOW_BOX.style_id: PRESET_VIBRANT_YELLOW_BOX,
    PRESET_VIBRANT_GREEN.style_id: PRESET_VIBRANT_GREEN,
    PRESET_VIBRANT_RED.style_id: PRESET_VIBRANT_RED,
}

# Compatibility aliases mapping old or variant IDs to registered presets
_STYLE_ALIASES: Dict[str, str] = {
    "default_bold_v1": "modern-box",
    "modern_box": "modern-box",
    "classic_outline": "classic-outline",
    "minimal_shadow": "minimal-shadow",
    "vibrant_cyan": "vibrant-cyan",
    "vibrant_yellow_box": "vibrant-yellow-box",
    "vibrant_green": "vibrant-green",
    "vibrant_red": "vibrant-red",
}

DEFAULT_STYLE_ID = "modern-box"


def list_caption_styles() -> List[CaptionStylePreset]:
    """Return all registered AutoShorts caption presets in recommended order."""
    return [
        PRESET_MODERN_BOX,
        PRESET_CLASSIC_OUTLINE,
        PRESET_MINIMAL_SHADOW,
        PRESET_VIBRANT_CYAN,
        PRESET_VIBRANT_YELLOW_BOX,
        PRESET_VIBRANT_GREEN,
        PRESET_VIBRANT_RED,
    ]


def get_caption_style(style_id: Optional[str] = None) -> CaptionStylePreset:
    """Retrieve CaptionStylePreset by identifier or alias.

    Falls back cleanly to DEFAULT_STYLE_ID (modern-box) if style_id is unknown or None.
    """
    if not style_id:
        return _STYLE_REGISTRY[DEFAULT_STYLE_ID]

    normalized_id = style_id.strip().lower().replace("_", "-")
    resolved_id = _STYLE_ALIASES.get(style_id.strip().lower(), normalized_id)

    if resolved_id in _STYLE_REGISTRY:
        return _STYLE_REGISTRY[resolved_id]

    # Safe fallback
    return _STYLE_REGISTRY[DEFAULT_STYLE_ID]


def resolve_caption_config(
    style_id: Optional[str] = None,
    canvas_width: int = 1080,
    overrides: Optional[CaptionConfig] = None,
) -> CaptionConfig:
    """Resolve and scale a CaptionConfig for a given output width.

    Follows AutoShorts proportional width scaling formula:
    fontsize = clamp(width * 0.075, 16, 80)
    padding = clamp(fontsize * 0.3, 4, 24)
    """
    preset = get_caption_style(style_id)
    cfg = overrides or preset.config.model_copy(deep=True)

    # Proportional width scaling: if width is not standard 1080, scale font size & padding
    if canvas_width != 1080:
        scaled_fontsize = int(round(max(16.0, min(80.0, canvas_width * 0.075))))
        cfg.font_size = scaled_fontsize
        if cfg.border_style == 3 and cfg.outline:
            scaled_padding = max(4.0, min(24.0, scaled_fontsize * 0.3))
            cfg.outline.width = scaled_padding

    return cfg
