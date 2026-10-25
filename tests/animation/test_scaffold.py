"""Scaffold verification tests for AI Animation Studio."""

from pathlib import Path
from app.ai_animation.config import get_animation_settings, AnimationSettings
from app.ai_animation.domain.models import (
    Script,
    ScriptSection,
    ScriptStatus,
    AssetManifest,
    AssetItem,
    ScenePlan,
    Scene,
    Beat,
    BeatSceneSpec,
    CoverageReport,
    AnimationRunManifest,
)
from app.ai_animation.api.routes import router


def test_animation_settings_env_prefix():
    """Verify animation settings use ANIM_ prefix and have sound defaults."""
    settings = get_animation_settings()
    assert settings.feature_name == "AI Animation Studio"
    assert settings.output_dir == Path("animation_outputs")
    assert settings.assets_dir.name == "ai_animation"
    assert settings.assets_dir.exists()
    assert settings.render_fps == 24
    assert settings.render_width == 1920
    assert settings.render_height == 1080


def test_animation_data_contract_models():
    """Verify Pydantic models for script, asset manifest, and scene plan validate cleanly."""
    script = Script(
        title="Why You Procrastinate",
        status=ScriptStatus.DRAFT,
        sections=[
            ScriptSection(id="sec_01", title="Hook", narration="Have you ever wondered why you put things off?"),
        ],
    )
    assert script.status == ScriptStatus.DRAFT
    assert len(script.sections) == 1

    manifest = AssetManifest(
        assets=[
            AssetItem(id="bg_room_01", type="background", description="Cozy bedroom with desk"),
            AssetItem(id="char_stick_01", type="character", description="Simple stick figure character"),
        ]
    )
    assert len(manifest.assets) == 2

    plan = ScenePlan(
        title="Why You Procrastinate",
        script_version=1,
        scenes=[
            Scene(
                id="scene_01",
                beats=[
                    Beat(
                        id="s01_b01",
                        narration="Have you ever wondered why you put things off?",
                        scene=BeatSceneSpec(background="bg_room_01"),
                    )
                ],
            )
        ],
    )
    assert len(plan.scenes) == 1
    assert plan.scenes[0].beats[0].scene.background == "bg_room_01"


def test_animation_router_endpoints():
    """Verify animation router is mounted with /animation prefix and contains health & config endpoints."""
    assert router.prefix == "/animation"
    route_paths = [r.path for r in router.routes]
    assert "/animation/health" in route_paths
    assert "/animation/config" in route_paths
