"""Unit tests for domain candidate scoring logic."""

import pytest
from app.domain.candidates.models import EditorialGoal, ScoreBreakdown
from app.domain.candidates.scoring import calculate_overall_score


def test_calculate_overall_score_perfect_ratings():
    # If all dimensions are 5.0, score must be 100
    breakdown = ScoreBreakdown(
        hook_strength=5.0,
        completeness_coherence=5.0,
        standalone_understandability=5.0,
        goal_relevance=5.0,
        goal_specific_impact=5.0,
        specificity_insight=5.0,
        pacing_conciseness=5.0,
        ending_quality=5.0,
    )
    score = calculate_overall_score(breakdown, goal=EditorialGoal.OVERALL)
    assert score == 100


def test_calculate_overall_score_zero_ratings():
    # If all dimensions are 0.0, score must be 0
    breakdown = ScoreBreakdown(
        hook_strength=0.0,
        completeness_coherence=0.0,
        standalone_understandability=0.0,
        goal_relevance=0.0,
        goal_specific_impact=0.0,
        specificity_insight=0.0,
        pacing_conciseness=0.0,
        ending_quality=0.0,
    )
    score = calculate_overall_score(breakdown, goal=EditorialGoal.OVERALL)
    assert score == 0


def test_goal_weight_influence():
    # A candidate with high hook strength but lower elsewhere should score higher in HOOK goal than EDUCATION goal
    breakdown = ScoreBreakdown(
        hook_strength=5.0,
        completeness_coherence=2.0,
        standalone_understandability=2.0,
        goal_relevance=2.0,
        goal_specific_impact=2.0,
        specificity_insight=1.0,
        pacing_conciseness=4.0,
        ending_quality=2.0,
    )
    hook_score = calculate_overall_score(breakdown, goal=EditorialGoal.HOOK)
    edu_score = calculate_overall_score(breakdown, goal=EditorialGoal.EDUCATION)

    assert hook_score > edu_score, f"Hook score ({hook_score}) should exceed education score ({edu_score})"
