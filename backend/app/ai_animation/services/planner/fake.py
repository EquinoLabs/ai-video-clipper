"""Fake LLM planner for offline development and testing.

Returns deterministic, schema-valid ScenePlan models and raw JSON dictionaries,
enabling offline development of asset coverage verification and scene rendering
without incurring LLM costs or requiring Ollama to be running.
"""

from typing import Any, Dict
from app.ai_animation.domain.models import (
    Beat,
    BeatSceneSpec,
    CharacterPlacement,
    Scene,
    ScenePlan,
)


def get_sample_scene_plan_dict() -> Dict[str, Any]:
    """Return raw sample JSON dictionary conforming strictly to scene_plan.json schema."""
    return {
        "schema_version": "v1.0",
        "title": "Why You Procrastinate",
        "script_version": 1,
        "scenes": [
            {
                "id": "scene_01",
                "title": "Hook & The Problem",
                "beats": [
                    {
                        "id": "s01_b01",
                        "narration": "Have you ever wondered why you put things off until the last possible minute?",
                        "scene": {
                            "layout": "medium_shot",
                            "background": "bg_bedroom_desk_01",
                            "characters": [
                                {
                                    "id": "narrator",
                                    "pose": "pose_point",
                                    "expression": "expr_curious",
                                    "position_x": 0.5,
                                }
                            ],
                            "props": ["prop_laptop_01", "prop_coffee_cup"],
                            "action": "none",
                            "camera": "static",
                        },
                    },
                    {
                        "id": "s01_b02",
                        "narration": "It turns out, procrastination isn't laziness. It's an emotional response.",
                        "scene": {
                            "layout": "close_up",
                            "background": "bg_bedroom_desk_01",
                            "characters": [
                                {
                                    "id": "narrator",
                                    "pose": "pose_explain",
                                    "expression": "expr_neutral",
                                    "position_x": 0.5,
                                }
                            ],
                            "props": ["prop_laptop_01"],
                            "action": "none",
                            "camera": "zoom_in",
                        },
                    },
                ],
            },
            {
                "id": "scene_02",
                "title": "The Science of Avoidance",
                "beats": [
                    {
                        "id": "s02_b01",
                        "narration": "Your brain perceives difficult tasks as threats, triggering immediate avoidance.",
                        "scene": {
                            "layout": "two_shot",
                            "background": "bg_office_01",
                            "characters": [
                                {
                                    "id": "narrator",
                                    "pose": "pose_explain",
                                    "expression": "expr_neutral",
                                    "position_x": 0.35,
                                },
                                {
                                    "id": "bystander_1",
                                    "pose": "pose_stress",
                                    "expression": "expr_worried",
                                    "position_x": 0.65,
                                },
                            ],
                            "props": ["prop_desk_stack_papers"],
                            "action": "none",
                            "camera": "pan_right",
                        },
                    }
                ],
            },
        ],
    }


class FakePlannerLLM:
    """Offline development planner producing deterministic, schema-valid ScenePlan instances."""

    def __init__(self, default_title: str = "Why You Procrastinate"):
        self.default_title = default_title

    def generate_sample_scene_plan(
        self,
        title: str = "Why You Procrastinate",
        script_version: int = 1,
    ) -> ScenePlan:
        """Return a deterministic, validated ScenePlan model instance."""
        data = get_sample_scene_plan_dict()
        data["title"] = title or self.default_title
        data["script_version"] = script_version
        return ScenePlan.model_validate(data)
