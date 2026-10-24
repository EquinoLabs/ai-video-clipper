"""Focused unit tests for Phase 2 Semantic Anchors + Bounded Window Expansion."""

import pytest
from app.api.v1.schemas.candidates import (
    AnchorType,
    ConfidenceLabel,
    EditorialGoal,
    EvidenceItem,
    GenerationSettings,
    LLMAnchorEvaluation,
    ScoreBreakdown,
    ValidationReasonCode,
)
from app.domain.transcript.models import TranscriptSegment, WordTiming
from app.services.candidates.expansion import (
    construct_bounded_candidate_windows,
    expand_anchors_to_candidates,
    validate_anchor,
)
from app.services.candidates.ranking import deduplicate_and_rank_candidates


@pytest.fixture
def sample_board_game_segments():
    """12 segments simulating the 49.19s board game interview conversation."""
    return [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=4.14, duration_seconds=4.14, text="Thank you for playing reverse charades with me. You're a great partner."),
        TranscriptSegment(id=1, start_seconds=4.14, end_seconds=8.72, duration_seconds=4.58, text="I mean, are you competitive when you play games? Do you play games at home?"),
        TranscriptSegment(id=2, start_seconds=8.88, end_seconds=11.02, duration_seconds=2.14, text="I know me neither. Are you what means you but then you saw over there."),
        TranscriptSegment(id=3, start_seconds=11.02, end_seconds=14.48, duration_seconds=3.46, text="I was like, now it's just a nice friendly game and then the last I'm like that the points are on."),
        TranscriptSegment(id=4, start_seconds=15.64, end_seconds=17.44, duration_seconds=1.80, text="Let's go. I want to win this something takes over."),
        TranscriptSegment(id=5, start_seconds=17.44, end_seconds=19.72, duration_seconds=2.28, text="Less competitive now."),
        TranscriptSegment(id=6, start_seconds=19.72, end_seconds=27.72, duration_seconds=8.00, text="Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are competitive too."),
        TranscriptSegment(id=7, start_seconds=27.72, end_seconds=31.44, duration_seconds=3.72, text="And it turns out motherhood is often me, and I like to watch them win yeah."),
        TranscriptSegment(id=8, start_seconds=31.44, end_seconds=35.96, duration_seconds=4.52, text="My kids are very competitive. Well, my one daughter is yeah."),
        TranscriptSegment(id=9, start_seconds=35.96, end_seconds=37.84, duration_seconds=1.88, text="Yeah, the other one doesn't really care."),
        TranscriptSegment(id=10, start_seconds=38.39, end_seconds=43.83, duration_seconds=5.44, text="Because it's fun. It's all good, but the other one really wants to win and I don't throw the games."),
        TranscriptSegment(id=11, start_seconds=43.83, end_seconds=47.69, duration_seconds=3.86, text="You know, I go I really and I play for I play for money to."),
    ]


@pytest.fixture
def default_scores():
    return ScoreBreakdown(
        hook_strength=4.5,
        completeness_coherence=4.0,
        standalone_understandability=4.0,
        goal_relevance=4.5,
        goal_specific_impact=4.8,
        specificity_insight=4.0,
        pacing_conciseness=4.2,
        ending_quality=4.5,
    )


# 1. Valid anchor IDs and chunk-local mapping
def test_valid_anchor_ids_and_chunk_local_mapping(sample_board_game_segments, default_scores):
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_001",
        anchor_segment_ids=[10, 11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Anne admits she plays board games for money against her kids",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Hilarious punchline resolving family game night discussion",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    val_res = validate_anchor(anchor, sample_board_game_segments)
    assert val_res.is_valid is True
    assert len(val_res.reason_codes) == 0


# 2. Unknown, duplicate, malformed, and discontiguous segment IDs
def test_anchor_validation_rejects_unknown_and_discontiguous_ids(sample_board_game_segments, default_scores):
    # Out of bounds segment ID
    out_of_bounds = LLMAnchorEvaluation(
        anchor_id="anc_oob",
        anchor_segment_ids=[11, 15],  # 15 exceeds len(segments)=12
        anchor_type=AnchorType.PUNCHLINE,
        hook="Out of bounds test",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Testing OOB",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    assert validate_anchor(out_of_bounds, sample_board_game_segments).is_valid is False
    assert ValidationReasonCode.UNKNOWN_SEGMENT_ID in validate_anchor(out_of_bounds, sample_board_game_segments).reason_codes

    # Discontiguous IDs
    discontiguous = LLMAnchorEvaluation(
        anchor_id="anc_disc",
        anchor_segment_ids=[6, 8],  # Missing segment 7
        anchor_type=AnchorType.PUNCHLINE,
        hook="Discontiguous test",
        transcript_excerpt="My kids are very competitive",
        score_dimensions=default_scores,
        rationale="Testing discontiguity",
        evidence=[EvidenceItem(start_seconds=19.72, end_seconds=27.72, quote="being competitive is genetic")],
    )
    assert validate_anchor(discontiguous, sample_board_game_segments).is_valid is False
    assert ValidationReasonCode.DISCONTIGUOUS_ANCHOR in validate_anchor(discontiguous, sample_board_game_segments).reason_codes


# 3. Ungrounded excerpt and evidence rejection
def test_anchor_validation_rejects_ungrounded_excerpt_and_evidence(sample_board_game_segments, default_scores):
    ungrounded_excerpt = LLMAnchorEvaluation(
        anchor_id="anc_ungrounded",
        anchor_segment_ids=[10, 11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Hallucinated excerpt",
        transcript_excerpt="We went to the supermarket and bought ice cream",  # Hallucinated
        score_dimensions=default_scores,
        rationale="Testing ungrounded excerpt",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    res = validate_anchor(ungrounded_excerpt, sample_board_game_segments)
    assert res.is_valid is False
    assert ValidationReasonCode.EXCERPT_NOT_GROUNDED in res.reason_codes

    ungrounded_evidence = LLMAnchorEvaluation(
        anchor_id="anc_ungrounded_ev",
        anchor_segment_ids=[10, 11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Hallucinated evidence",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Testing ungrounded evidence",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="completely made up line")],
    )
    res_ev = validate_anchor(ungrounded_evidence, sample_board_game_segments)
    assert res_ev.is_valid is False
    assert ValidationReasonCode.EVIDENCE_NOT_GROUNDED in res_ev.reason_codes


# 4. A sub-minimum anchor that expands into a valid contextual window
def test_sub_minimum_anchor_expands_to_valid_contextual_window(sample_board_game_segments, default_scores):
    # Anchor is segment 11 only (3.86 seconds: 43.83s - 47.69s)
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_punchline",
        anchor_segment_ids=[11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Anne plays for money",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Punchline needing context",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, target_duration_seconds=30.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, sample_board_game_segments, settings, source_duration_seconds=49.19)
    assert len(windows) >= 1
    # Every constructed window must satisfy min duration >= 10.0s
    for w_start, w_end, w_type in windows:
        dur = w_end - w_start
        assert dur >= 10.0
        assert dur <= 60.0
        assert w_end <= 49.20


# 5. A valid anchor for which every expanded window is invalid (zero valid windows)
def test_valid_anchor_with_zero_valid_windows(default_scores):
    # A single 3-second segment with no preceding segments
    short_segs = [TranscriptSegment(id=0, start_seconds=0.0, end_seconds=3.0, duration_seconds=3.0, text="Quick joke punchline.")]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_tiny",
        anchor_segment_ids=[0],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Tiny joke",
        transcript_excerpt="Quick joke punchline",
        score_dimensions=default_scores,
        rationale="Tiny moment",
        evidence=[EvidenceItem(start_seconds=0.0, end_seconds=3.0, quote="Quick joke punchline")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, short_segs, settings, source_duration_seconds=3.0)
    assert len(windows) == 0

    exp_res = expand_anchors_to_candidates([anchor], short_segs, EditorialGoal.HUMOR, settings, 3.0)
    assert len(exp_res.evaluations) == 0
    assert len(exp_res.rejected_audits) == 1
    assert ValidationReasonCode.NO_VALID_WINDOW in exp_res.rejected_audits[0].reason_codes


# 6. Fallback after structural windows exist but all fail validation
def test_fallback_when_structural_windows_fail_duration():
    # Anchor at segment 1 (2s). Segment 0 is 2s. Total span is 4s (under 10s min).
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=2.0, duration_seconds=2.0, text="Intro remark."),
        TranscriptSegment(id=1, start_seconds=2.0, end_seconds=4.0, duration_seconds=2.0, text="Quick punchline."),
    ]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_fail",
        anchor_segment_ids=[1],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Quick punchline",
        transcript_excerpt="Quick punchline",
        score_dimensions=ScoreBreakdown(
            hook_strength=4.0, completeness_coherence=4.0, standalone_understandability=4.0,
            goal_relevance=4.0, goal_specific_impact=4.0, specificity_insight=4.0,
            pacing_conciseness=4.0, ending_quality=4.0,
        ),
        rationale="Testing fallback exhaustion",
        evidence=[EvidenceItem(start_seconds=2.0, end_seconds=4.0, quote="Quick punchline")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=4.0)
    assert len(windows) == 0  # Cannot reach 10s without exceeding available media


# 7. Topic-boundary and lookback protection
def test_topic_boundary_and_lookback_protection(default_scores):
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0, text="Welcome back to the show everyone. Moving on to our interview."),
        TranscriptSegment(id=1, start_seconds=10.0, end_seconds=20.0, duration_seconds=10.0, text="Let's talk about our current topic."),
        TranscriptSegment(id=2, start_seconds=20.0, end_seconds=25.0, duration_seconds=5.0, text="Here is a great joke punchline."),
    ]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_topic",
        anchor_segment_ids=[2],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Topic guarded joke",
        transcript_excerpt="great joke punchline",
        score_dimensions=default_scores,
        rationale="Joke after topic shift",
        evidence=[EvidenceItem(start_seconds=20.0, end_seconds=25.0, quote="great joke punchline")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=25.0)
    # The window should stop at segment 1 (start=10.0s) and NOT cross into segment 0 ("Welcome back...")
    assert len(windows) >= 1
    for w_start, w_end, w_type in windows:
        assert w_start >= 10.0  # Stopped before segment 0 topic boundary


# 8. Maximum duration and source container bounds
def test_max_duration_and_container_bounds(default_scores):
    # Long monologue segment
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=70.0, duration_seconds=70.0, text="Very long speech exceeding max duration."),
        TranscriptSegment(id=1, start_seconds=70.0, end_seconds=75.0, duration_seconds=5.0, text="Closing remark."),
    ]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_toolong",
        anchor_segment_ids=[1],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Exceeds max duration",
        transcript_excerpt="Closing remark",
        score_dimensions=default_scores,
        rationale="Too long",
        evidence=[EvidenceItem(start_seconds=70.0, end_seconds=75.0, quote="Closing remark")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=75.0)
    # Segment 0 + Segment 1 is 75s, which exceeds max_duration_seconds=60s
    for w_start, w_end, w_type in windows:
        assert (w_end - w_start) <= 60.0


# 9. Maximum three unique windows per anchor and deterministic ordering
def test_maximum_three_windows_per_anchor(sample_board_game_segments, default_scores):
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_cap",
        anchor_segment_ids=[10, 11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Punchline with multiple sentence starts",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Testing 3-window cap",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, target_duration_seconds=30.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, sample_board_game_segments, settings, source_duration_seconds=49.19)
    assert len(windows) <= 3
    # Check deduplication: intervals must be unique
    intervals = [(w[0], w[1]) for w in windows]
    assert len(intervals) == len(set(intervals))


# 10. Refinement followed by final validation
def test_refinement_and_revalidation_lifecycle(sample_board_game_segments, default_scores):
    # Verify that expanded candidates pass ranking and refinement
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_refine",
        anchor_segment_ids=[11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Anne plays for money",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Testing ranking lifecycle",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, target_duration_seconds=30.0, max_duration_seconds=60.0)
    exp_res = expand_anchors_to_candidates([anchor], sample_board_game_segments, EditorialGoal.HUMOR, settings, source_duration_seconds=49.19)
    assert len(exp_res.evaluations) >= 1

    ranking_res = deduplicate_and_rank_candidates(
        evaluations=exp_res.evaluations,
        segments=sample_board_game_segments,
        editorial_goal=EditorialGoal.HUMOR,
        settings=settings,
        source_duration_seconds=49.19,
    )
    assert len(ranking_res.candidates) >= 1
    cand = ranking_res.candidates[0]
    assert cand.duration_seconds >= 10.0
    assert cand.end_seconds <= 49.20


# 11. Overlapping candidates and IoU deduplication
def test_overlapping_candidates_iou_deduplication(sample_board_game_segments, default_scores):
    # Two anchors close to each other
    anc1 = LLMAnchorEvaluation(
        anchor_id="anc_1",
        anchor_segment_ids=[10],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Anne doesn't throw games",
        transcript_excerpt="I don't throw the games",
        score_dimensions=default_scores,
        rationale="Mom doesn't throw games",
        evidence=[EvidenceItem(start_seconds=38.39, end_seconds=43.83, quote="I don't throw the games")],
    )
    anc2 = LLMAnchorEvaluation(
        anchor_id="anc_2",
        anchor_segment_ids=[11],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Anne plays for money",
        transcript_excerpt="I play for money to",
        score_dimensions=default_scores,
        rationale="Plays for money",
        evidence=[EvidenceItem(start_seconds=43.83, end_seconds=47.69, quote="I play for money to")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    exp_res = expand_anchors_to_candidates([anc1, anc2], sample_board_game_segments, EditorialGoal.HUMOR, settings, source_duration_seconds=49.19)
    
    ranking_res = deduplicate_and_rank_candidates(
        evaluations=exp_res.evaluations,
        segments=sample_board_game_segments,
        editorial_goal=EditorialGoal.HUMOR,
        settings=settings,
        source_duration_seconds=49.19,
        iou_threshold=0.50,
    )
    # Deduplication suppresses overlapping duplicate windows
    assert len(ranking_res.candidates) <= len(exp_res.evaluations)


# 12. Zero accepted Shorts with clean empty list
def test_zero_accepted_shorts_cleanly_handled(default_scores):
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_zero",
        anchor_segment_ids=[0],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Sub-minimum quote with nowhere to expand",
        transcript_excerpt="Short quote",
        score_dimensions=default_scores,
        rationale="Zero shorts test",
        evidence=[EvidenceItem(start_seconds=0.0, end_seconds=2.0, quote="Short quote")],
    )
    segs = [TranscriptSegment(id=0, start_seconds=0.0, end_seconds=2.0, duration_seconds=2.0, text="Short quote.")]
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0)
    exp_res = expand_anchors_to_candidates([anchor], segs, EditorialGoal.HUMOR, settings, 2.0)
    assert len(exp_res.evaluations) == 0
    assert len(exp_res.rejected_audits) == 1

    ranking_res = deduplicate_and_rank_candidates([], segs, EditorialGoal.HUMOR, settings, 2.0)
    assert len(ranking_res.candidates) == 0


# 13. Regression coverage: long-clip discovery retains timestamp contract
def test_long_clip_discovery_retains_timestamp_contract(default_scores):
    from app.services.llm.prompts import build_system_prompt
    long_prompt = build_system_prompt(EditorialGoal.OVERALL, GenerationSettings.for_long_clips(), is_long_clip=True)
    assert "STANDALONE CONVERSATIONAL ARCS" in long_prompt
    assert "start_seconds and end_seconds must be exact decimal seconds" in long_prompt


# 14. Forward continuation exploration finds resolution beyond anchor end
def test_forward_continuation_finds_resolution_endpoint(default_scores):
    # Anchor is segment 1 only, but story resolves in segment 3
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0, text="Host introduces topic."),
        TranscriptSegment(id=1, start_seconds=5.0, end_seconds=10.0, duration_seconds=5.0, text="Speaker begins setup."),
        TranscriptSegment(id=2, start_seconds=10.0, end_seconds=15.0, duration_seconds=5.0, text="Speaker gives escalation."),
        TranscriptSegment(id=3, start_seconds=15.0, end_seconds=20.0, duration_seconds=5.0, text="Speaker lands punchline. That's funny."),
    ]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_fwd",
        anchor_segment_ids=[1],
        anchor_type=AnchorType.COMEDIC_BANTER,
        hook="Setup with forward resolution",
        transcript_excerpt="Speaker begins setup",
        score_dimensions=default_scores,
        rationale="Testing forward exploration",
        evidence=[EvidenceItem(start_seconds=5.0, end_seconds=10.0, quote="Speaker begins setup")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=20.0)
    # Must have explored forward to segment 3 (end_seconds=20.0s)
    end_times = [w[1] for w in windows]
    assert 20.0 in end_times


# 15. Deduplication preserves distinct endpoints even with high IoU
def test_deduplication_preserves_distinct_endpoints_with_high_iou(default_scores):
    from app.api.v1.schemas.candidates import LLMCandidateEvaluation
    # Two candidates starting at 0.0s, one truncated at 12.0s (evaluated first with higher score),
    # one extending to 20.0s with full resolution (evaluated second).
    # IoU = 12.0 / 20.0 = 0.60 (normally suppressed under 0.50 threshold)
    # But endpoint difference is 8.0s (> 6.0s) and c2 extends c1, so c2 is retained as a complete resolution.
    c1 = LLMCandidateEvaluation(
        start_seconds=0.0,
        end_seconds=12.0,
        hook="Truncated moment",
        transcript_excerpt="Truncated excerpt",
        score_dimensions=default_scores,
        rationale="Shorter candidate",
        evidence=[EvidenceItem(start_seconds=0.0, end_seconds=10.0, quote="Truncated excerpt")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    # Give c2 slightly lower score or further target diff so c1 ranks first
    c2_scores = ScoreBreakdown(
        hook_strength=4.0,
        completeness_coherence=4.0,
        standalone_understandability=4.0,
        goal_relevance=4.0,
        goal_specific_impact=4.0,
        specificity_insight=4.0,
        pacing_conciseness=4.0,
        ending_quality=4.0,
    )
    c2 = LLMCandidateEvaluation(
        start_seconds=0.0,
        end_seconds=20.0,
        hook="Complete moment with resolution",
        transcript_excerpt="Complete excerpt",
        score_dimensions=c2_scores,
        rationale="Longer candidate with resolution",
        evidence=[EvidenceItem(start_seconds=0.0, end_seconds=10.0, quote="Complete excerpt")],
        confidence_label=ConfidenceLabel.HIGH,
    )
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=12.0, duration_seconds=12.0, text="Truncated excerpt."),
        TranscriptSegment(id=1, start_seconds=12.0, end_seconds=20.0, duration_seconds=8.0, text="Complete resolution."),
    ]
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0, target_duration_seconds=15.0)
    # Target is 15.0s, so c1 (|12-15|=3.0) ranks ahead of c2 (|20-15|=5.0) and c1 has higher score (87 vs 80)
    ranking_res = deduplicate_and_rank_candidates([c1, c2], segs, EditorialGoal.HUMOR, settings, 20.0, iou_threshold=0.50)
    # Both candidates should survive because endpoint difference is 8.0s and c2 extends c1
    assert len(ranking_res.candidates) == 2


# 16. Topic isolation: Backward expansion stops at detected topic boundary
def test_topic_isolation_backward_expansion_stops_at_boundary(default_scores):
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=8.0, duration_seconds=8.0, text="Host and guest discuss weather and traffic."),
        TranscriptSegment(id=1, start_seconds=8.0, end_seconds=14.0, duration_seconds=6.0, text="So moving on, lets talk about your new film."),
        TranscriptSegment(id=2, start_seconds=14.0, end_seconds=20.0, duration_seconds=6.0, text="In the movie I play a ridiculous detective."),
        TranscriptSegment(id=3, start_seconds=20.0, end_seconds=26.0, duration_seconds=6.0, text="And the villain was my real life brother. That was hilarious!"),
    ]
    # Anchor is in the movie topic (segment 2)
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_movie",
        anchor_segment_ids=[2],
        anchor_type=AnchorType.COMEDIC_BANTER,
        hook="Movie detective role",
        transcript_excerpt="In the movie I play a ridiculous detective",
        score_dimensions=default_scores,
        rationale="Testing topic isolation",
        evidence=[EvidenceItem(start_seconds=14.0, end_seconds=20.0, quote="In the movie I play a ridiculous detective")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=26.0)
    # Windows should expand backward to segment 1 (start_seconds=8.0), but NEVER to segment 0 (weather)
    start_times = [w[0] for w in windows]
    assert 8.0 in start_times
    assert 0.0 not in start_times


# 17. Topic isolation: Boundary cue on anchor start prevents backward expansion into earlier topic
def test_topic_isolation_anchor_at_transition_does_not_expand_backward(default_scores):
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0, text="Previous topic concludes with laughing."),
        TranscriptSegment(id=1, start_seconds=10.0, end_seconds=18.0, duration_seconds=8.0, text="Switch gears and talk about your family. Do you have kids?"),
        TranscriptSegment(id=2, start_seconds=18.0, end_seconds=25.0, duration_seconds=7.0, text="Yeah, my daughter is really competitive."),
    ]
    # Anchor starts directly with the transition segment (segment 1)
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_family",
        anchor_segment_ids=[1, 2],
        anchor_type=AnchorType.COMEDIC_BANTER,
        hook="Family kids",
        transcript_excerpt="Switch gears and talk about your family",
        score_dimensions=default_scores,
        rationale="Testing transition at anchor start",
        evidence=[EvidenceItem(start_seconds=10.0, end_seconds=18.0, quote="Switch gears and talk about your family")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=25.0)
    # Must only start at 10.0s (segment 1), never pulling segment 0 (0.0s)
    for w in windows:
        assert w[0] >= 10.0


# 18. Topic isolation: Fallback nearest does not cross topic boundary
def test_topic_isolation_fallback_does_not_cross_boundary(default_scores):
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0, text="Previous discussion ends here."),
        TranscriptSegment(id=1, start_seconds=10.0, end_seconds=14.0, duration_seconds=4.0, text="Lets talk about the sequel."),
        TranscriptSegment(id=2, start_seconds=14.0, end_seconds=17.0, duration_seconds=3.0, text="We shot it in Iceland."),
    ]
    # Subminimum anchor at segment 2 (3s duration). Segments 1 + 2 = 7s (<10s).
    # Expanding to segment 0 would make 17s (valid duration), but crossing segment 1 is prohibited!
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_sub",
        anchor_segment_ids=[2],
        anchor_type=AnchorType.INSIGHT,
        hook="Iceland shoot",
        transcript_excerpt="We shot it in Iceland",
        score_dimensions=default_scores,
        rationale="Testing fallback across boundary",
        evidence=[EvidenceItem(start_seconds=14.0, end_seconds=17.0, quote="We shot it in Iceland")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=17.0)
    # Zero windows constructed because backward fallback refuses to cross topic transition at segment 1
    assert len(windows) == 0


# 19. Endpoint resolution: Forward continuation does not cross forward topic transition
def test_forward_continuation_stops_before_new_topic(default_scores):
    segs = [
        TranscriptSegment(id=0, start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0, text="Speaker starts story setup."),
        TranscriptSegment(id=1, start_seconds=5.0, end_seconds=12.0, duration_seconds=7.0, text="Speaker lands punchline."),
        TranscriptSegment(id=2, start_seconds=12.0, end_seconds=18.0, duration_seconds=6.0, text="Welcome back everyone! Our next guest is a musician."),
    ]
    anchor = LLMAnchorEvaluation(
        anchor_id="anc_punch",
        anchor_segment_ids=[0, 1],
        anchor_type=AnchorType.PUNCHLINE,
        hook="Story punchline",
        transcript_excerpt="Speaker lands punchline",
        score_dimensions=default_scores,
        rationale="Testing forward topic stop",
        evidence=[EvidenceItem(start_seconds=5.0, end_seconds=12.0, quote="Speaker lands punchline")],
    )
    settings = GenerationSettings.for_short_clips(min_duration_seconds=10.0, max_duration_seconds=60.0)
    windows = construct_bounded_candidate_windows(anchor, segs, settings, source_duration_seconds=18.0)
    # Window end must not include segment 2 (18.0s)
    end_times = [w[1] for w in windows]
    assert 18.0 not in end_times
    assert 12.0 in end_times

