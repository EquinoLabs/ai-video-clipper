"""Domain logic for candidate scoring and goal-conditioned weight calculation."""

from typing import Dict
from app.ai_clipper.domain.candidates.models import EditorialGoal, ScoreBreakdown

# Versioned goal weights for scoring dimensions (sum to 1.0)
GOAL_WEIGHTS_V1: Dict[EditorialGoal, Dict[str, float]] = {
    EditorialGoal.OVERALL: {
        "hook_strength": 0.20,
        "completeness_coherence": 0.20,
        "standalone_understandability": 0.15,
        "goal_relevance": 0.10,
        "goal_specific_impact": 0.10,
        "specificity_insight": 0.10,
        "pacing_conciseness": 0.08,
        "ending_quality": 0.07,
    },
    EditorialGoal.HOOK: {
        "hook_strength": 0.35,
        "pacing_conciseness": 0.15,
        "completeness_coherence": 0.15,
        "goal_specific_impact": 0.15,
        "standalone_understandability": 0.10,
        "goal_relevance": 0.05,
        "specificity_insight": 0.03,
        "ending_quality": 0.02,
    },
    EditorialGoal.HUMOR: {
        "goal_specific_impact": 0.30,  # Punchline / comedic timing
        "pacing_conciseness": 0.15,
        "hook_strength": 0.15,
        "completeness_coherence": 0.15,
        "standalone_understandability": 0.10,
        "ending_quality": 0.07,
        "goal_relevance": 0.05,
        "specificity_insight": 0.03,
    },
    EditorialGoal.EDUCATION: {
        "specificity_insight": 0.25,
        "standalone_understandability": 0.20,
        "completeness_coherence": 0.20,
        "goal_relevance": 0.15,
        "goal_specific_impact": 0.10,
        "hook_strength": 0.05,
        "ending_quality": 0.03,
        "pacing_conciseness": 0.02,
    },
    EditorialGoal.EMOTION: {
        "goal_specific_impact": 0.30,
        "hook_strength": 0.15,
        "completeness_coherence": 0.15,
        "standalone_understandability": 0.15,
        "goal_relevance": 0.10,
        "specificity_insight": 0.05,
        "ending_quality": 0.05,
        "pacing_conciseness": 0.05,
    },
    EditorialGoal.THOUGHT_PROVOKING: {
        "specificity_insight": 0.25,
        "goal_specific_impact": 0.20,
        "hook_strength": 0.15,
        "standalone_understandability": 0.15,
        "completeness_coherence": 0.15,
        "goal_relevance": 0.05,
        "pacing_conciseness": 0.03,
        "ending_quality": 0.02,
    },
    EditorialGoal.CUSTOM: {
        "goal_relevance": 0.25,
        "goal_specific_impact": 0.20,
        "hook_strength": 0.15,
        "completeness_coherence": 0.15,
        "standalone_understandability": 0.10,
        "specificity_insight": 0.05,
        "pacing_conciseness": 0.05,
        "ending_quality": 0.05,
    },
}


def calculate_overall_score(
    breakdown: ScoreBreakdown,
    goal: EditorialGoal = EditorialGoal.OVERALL,
    version: str = "v1.0",
) -> int:
    """Calculate the 0-100 overall score from 0-5 dimension ratings using goal weights.

    Each dimension is rated 0.0 to 5.0.
    Weighted average on 0..5 scale is normalized to 0..100: (weighted_sum / 5.0) * 100.
    """
    weights = GOAL_WEIGHTS_V1.get(goal, GOAL_WEIGHTS_V1[EditorialGoal.OVERALL])
    ratings = breakdown.model_dump()

    weighted_sum = sum(ratings[dim] * weight for dim, weight in weights.items())
    normalized_score = (weighted_sum / 5.0) * 100.0

    return max(0, min(100, round(normalized_score)))
