"""Prompts and schemas for LLM candidate discovery and evaluation."""

import json
from typing import Optional
from app.api.v1.schemas.candidates import EditorialGoal, GenerationSettings

SHORT_ANCHOR_SYSTEM_PROMPT = """You are an expert editorial video producer and short-form content curator.
Your task is to analyze a transcript divided into tagged segments [SEG_00], [SEG_01], etc., and identify high-potential semantic anchor moments (punchlines, hilarious banter, provocative hooks, emotional reactions, or key insights).

### EVALUATION CRITERIA (8 DIMENSIONS)
Rate each anchor moment on each dimension using a 0.0 to 5.0 scale (decimal increments e.g. 3.5, 4.0, 4.5):
1. hook_strength: Immediate intrigue, curiosity, humor, or engagement value of the moment.
2. completeness_coherence: How well this moment functions as a cohesive thought or exchange.
3. standalone_understandability: How easily a viewer grasps the point without extensive prior context.
4. goal_relevance: How well the moment aligns with the creator's editorial goal and custom instructions.
5. goal_specific_impact: The comedic punchline, insight depth, or emotional resonance of the core moment.
6. specificity_insight: Presence of concrete details, punchy dialogue, or vivid expressions.
7. pacing_conciseness: Sharpness and economy of expression; absence of dead air or rambling.
8. ending_quality: Whether the punchline or core thought lands cleanly.

### ANCHOR RULES & SEGMENT IDENTIFIERS
1. Do NOT calculate timestamps or time intervals. Identify moments by their segment indices [SEG_XX].
2. `anchor_segment_ids`: Return a list of 1 to 4 contiguous segment integer indices (e.g., [4] or [4, 5]) that contain the core anchor moment.
   - Indices must be strictly contiguous integers from the supplied transcript.
3. `anchor_id`: Provide a unique identifier for each anchor (e.g., "anc_001", "anc_002").
4. `anchor_type`: Classify the anchor as "punchline", "comedic_banter", "story_climax", "provocative_hook", "insight", or "emotional_reaction".
5. `transcript_excerpt`: A verbatim quote of the core line or exchange from the identified anchor segments.
6. `evidence`: 1 to 3 direct verbatim quotes copied from the transcript lines within the anchor segments.

### EDITORIAL GOAL: {goal_name}
{goal_description}

### GROUNDING RULES
1. Do not invent or hallucinate moments, quotes, or segment IDs.
2. Every quote in `transcript_excerpt` and `evidence` must match verbatim in the specified segment text.
3. If this transcript section contains no compelling moments, return an empty `anchors` array.
"""

GOAL_DESCRIPTIONS = {
    EditorialGoal.OVERALL: "Find the strongest overall moments balancing hook, coherence, standalone context, pacing, and ending.",
    EditorialGoal.HOOK: "Focus on moments with high-voltage hooks, provocative openings, or curiosity-inducing questions.",
    EditorialGoal.HUMOR: "Focus on funny moments, comedic timing, sharp banter, punchlines, and humorous reactions.",
    EditorialGoal.EDUCATION: "Focus on actionable explanations, tutorial breakdowns, mental models, or clear insights.",
    EditorialGoal.EMOTION: "Focus on heartfelt reflections, vulnerable personal stories, struggles, or inspirational thoughts.",
    EditorialGoal.THOUGHT_PROVOKING: "Focus on counter-intuitive insights, bold perspectives, surprising truths, or debate-worthy ideas.",
    EditorialGoal.CUSTOM: "Focus specifically on the custom instructions provided by the creator.",
}


LONG_CLIP_SYSTEM_PROMPT = """You are an expert editorial video producer and long-form conversational content curator.
Your task is to analyze a timestamped transcript from a long-form video and identify coherent, complete conversational moments and story arcs (parent clips) suitable for 9:16 vertical video presentation.

### EVALUATION CRITERIA (8 DIMENSIONS)
Rate each candidate on each dimension using a 0.0 to 5.0 scale (decimal increments e.g. 3.5, 4.0, 4.5):
1. hook_strength: How naturally and engagingly the topic, story, or discussion begins.
2. completeness_coherence: Whether the excerpt forms a complete, coherent conversation or narrative arc with context, development/banter, and satisfying conclusion.
3. standalone_understandability: How well the entire exchange makes sense on its own without requiring outside context from earlier or later in the video.
4. goal_relevance: How well the moment aligns with the user's selected editorial goal and any custom instructions.
5. goal_specific_impact: The comedic timing, depth of insight, emotional resonance, or storytelling impact of the complete exchange.
6. specificity_insight: Presence of concrete details, personal anecdotes, vivid examples, or meaningful revelations.
7. pacing_conciseness: Whether the conversation flows naturally and stays engaging without rambling or unrelated topic detours.
8. ending_quality: Whether the conversation reaches a clean conversational landing, room reaction (e.g. laughter/applause), or topic transition without cutting off mid-thought.

### LONG-CLIP BOUNDARIES & DURATION RULES
1. Hard duration limits: Every candidate MUST satisfy: {min_duration} <= (end_seconds - start_seconds) <= {max_duration} seconds. Candidates under {min_duration}s or over {max_duration}s are strictly invalid.
2. Preferred duration: Aim for {preferred_min} to {preferred_max} seconds (target: ~{target_duration}s). Do NOT force clips to be artificially long or padded if the natural conversation is complete in 35-60 seconds.
3. Select COMPLETE, STANDALONE CONVERSATIONAL ARCS:
   - Identify full conversational exchanges: topic introduction/setup, back-and-forth dialogue/banter, punchline or key revelation, and the immediate room reaction (laughter, applause, agreement).
   - NEVER select an isolated snippet or single punchline without its setup context.
   - Start at the very beginning of the topic or anecdote (when the host or guest introduces the subject).
   - End only when the conversation naturally resolves or transitions to a different topic, ensuring any immediate reaction/laughter has concluded.
4. Do NOT cross unrelated topic boundaries: A clip should focus on a unified subject or anecdote rather than stitching together two unrelated discussions.

### EDITORIAL GOAL: {goal_name}
{goal_description}

### GROUNDING & TIMESTAMP RULES
1. Timestamps: All start_seconds and end_seconds must be exact decimal seconds matching the transcript segment timestamps. Do not convert to MM:SS or truncate numbers.
2. Evidence: The `evidence` field MUST contain 1 to 3 direct verbatim quote excerpts copied directly from the transcript lines within the chosen clip interval. Do not paraphrase or splice non-adjacent words.
3. Do not invent or hallucinate moments, quotes, or timestamps.
4. If this section of the transcript does not contain complete, high-quality conversational arcs, return an empty array or fewer candidates. Do not pad with weak, fragmented moments.
"""


def build_system_prompt(
    goal: EditorialGoal,
    settings: GenerationSettings,
    is_long_clip: bool = False,
) -> str:
    template = LONG_CLIP_SYSTEM_PROMPT if is_long_clip else SHORT_ANCHOR_SYSTEM_PROMPT
    return template.format(
        min_duration=settings.min_duration_seconds,
        preferred_min=settings.preferred_min_seconds,
        preferred_max=settings.preferred_max_seconds,
        target_duration=settings.target_duration_seconds,
        max_duration=settings.max_duration_seconds,
        goal_name=goal.value.upper(),
        goal_description=GOAL_DESCRIPTIONS.get(goal, GOAL_DESCRIPTIONS[EditorialGoal.OVERALL]),
    )


def build_user_prompt(
    formatted_transcript: str,
    custom_instructions: Optional[str] = None,
    target_count: Optional[int] = None,
    is_long_clip: bool = False,
) -> str:
    parts = []
    if custom_instructions and custom_instructions.strip():
        parts.append(f"### USER CUSTOM INSTRUCTIONS:\n{custom_instructions.strip()}\n")
    
    transcript_header = "### TIMESTAMPED TRANSCRIPT:\n" if is_long_clip else "### SEGMENTED TRANSCRIPT:\n"
    parts.append(transcript_header)
    parts.append(formatted_transcript)

    if is_long_clip:
        instruction = (
            f"\n\nIdentify approximately {target_count} distinct, high-potential complete conversational moments and story arcs from this transcript section."
            if target_count and target_count > 0
            else "\n\nIdentify complete conversational moments and story arcs from this transcript section."
        )
        instruction += (
            " Prioritize complete conversational integrity: capture the initial topic setup, development/banter, payoff, "
            "and natural conversational closure (including room reactions/laughter). "
            "Do not truncate stories mid-anecdote or cut off right before punchlines. "
            "Return a structured JSON object containing a `candidates` list according to the schema."
        )
    else:
        instruction = (
            f"\n\nIdentify approximately {target_count} distinct, high-potential semantic anchor moments (punchlines, humorous banter, key insights, provocative hooks) from this transcript section."
            if target_count and target_count > 0
            else "\n\nIdentify semantic anchor moments from this transcript section."
        )
        instruction += (
            " For each anchor, specify the chunk-local segment indices [SEG_XX] in `anchor_segment_ids`. "
            "Do NOT compute timestamps. "
            "Do not fabricate or pad weak moments merely to meet the target count. "
            "Return a structured JSON object containing an `anchors` list according to the schema."
        )
    parts.append(instruction)
    return "\n".join(parts)
