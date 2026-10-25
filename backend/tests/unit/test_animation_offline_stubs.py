"""Unit tests for Animation Studio offline development stubs (FakeTTSProvider & FakePlannerLLM)."""

import tempfile
import wave
from pathlib import Path
import pytest

from app.ai_animation.domain.models import ScenePlan
from app.ai_animation.services.planner.fake import FakePlannerLLM, get_sample_scene_plan_dict
from app.ai_animation.services.tts.fake import FakeTTSProvider


def test_fake_tts_synthesize_silence(tmp_path: Path):
    """Verify FakeTTSProvider produces valid 16-bit PCM silence WAV of exact requested duration."""
    tts = FakeTTSProvider(sample_rate=24000, channels=1, sampwidth=2)
    out_file = tmp_path / "silence_test.wav"

    duration = 2.5
    result_path = tts.synthesize_silence(duration_seconds=duration, output_path=out_file)

    assert result_path.exists()
    assert result_path.stat().st_size > 0

    with wave.open(str(result_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000
        n_frames = wf.getnframes()
        assert n_frames == int(round(duration * 24000))
        # Ensure audio content is zeroed silence
        frames = wf.readframes(n_frames)
        assert frames == b"\x00" * (n_frames * 2)


def test_fake_tts_rejects_negative_duration(tmp_path: Path):
    """Verify FakeTTSProvider rejects negative durations."""
    tts = FakeTTSProvider()
    with pytest.raises(ValueError):
        tts.synthesize_silence(duration_seconds=-1.0, output_path=tmp_path / "neg.wav")


def test_fake_planner_llm_deterministic_output():
    """Verify FakePlannerLLM returns a schema-valid ScenePlan matching PRD data contracts."""
    planner = FakePlannerLLM()
    plan = planner.generate_sample_scene_plan(title="The Power of Habit", script_version=2)

    assert isinstance(plan, ScenePlan)
    assert plan.title == "The Power of Habit"
    assert plan.script_version == 2
    assert len(plan.scenes) == 2

    # Verify first scene and beat structure
    scene_1 = plan.scenes[0]
    assert scene_1.id == "scene_01"
    assert len(scene_1.beats) == 2
    beat_1 = scene_1.beats[0]
    assert beat_1.id == "s01_b01"
    assert "Have you ever wondered" in beat_1.narration
    assert beat_1.scene.background == "bg_bedroom_desk_01"
    assert len(beat_1.scene.characters) == 1
    assert beat_1.scene.characters[0].id == "narrator"
    assert beat_1.scene.characters[0].pose == "pose_point"

    # Verify second scene multi-character composition
    scene_2 = plan.scenes[1]
    assert scene_2.id == "scene_02"
    beat_2 = scene_2.beats[0]
    assert beat_2.scene.background == "bg_office_01"
    assert len(beat_2.scene.characters) == 2


def test_sample_scene_plan_dict_validates_cleanly():
    """Verify raw sample scene plan dictionary validates without error."""
    raw_dict = get_sample_scene_plan_dict()
    validated = ScenePlan.model_validate(raw_dict)
    assert validated.schema_version == "v1.0"
    assert validated.title == "Why You Procrastinate"
