"""Unit tests for AI Animation Studio scaffold."""

import json
from pathlib import Path
from app.ai_animation.config import get_animation_settings
from app.ai_animation.domain.models import Script, ScriptStatus, AssetManifest, AssetItem, ScenePlan
from app.ai_animation.api.routes import router


def test_animation_settings_scaffold():
    settings = get_animation_settings()
    assert settings.feature_name == "AI Animation Studio"
    assert settings.output_dir == Path("animation_outputs")
    assert settings.render_fps == 24
    assert settings.assets_dir.exists()
    assert (settings.assets_dir / "manifest.json").exists()


def test_animation_asset_manifest_readability():
    settings = get_animation_settings()
    manifest_file = settings.assets_dir / "manifest.json"
    assert manifest_file.exists()
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "v1.0"
    manifest = AssetManifest.model_validate(data)
    assert isinstance(manifest.assets, list)


def test_animation_router_prefix():
    assert router.prefix == "/animation"
    paths = [r.path for r in router.routes]
    assert "/animation/health" in paths
    assert "/animation/config" in paths
