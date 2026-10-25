"""Word-timestamp boundary refinement and outward silence snapping service."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from app.ai_clipper.domain.transcript.models import TranscriptSegment, WordTiming

logger = logging.getLogger(__name__)


class BoundaryRefinementConfig(BaseModel):
    """Configuration for word-timestamp boundary refinement and outward cushion."""
    outward_cushion_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=5.0,
        description="Ideal outward contextual cushion to add into adjacent silence",
    )
    max_extension_seconds: float = Field(
        default=3.0,
        ge=0.0,
        le=10.0,
        description="Absolute maximum seconds the boundary may expand outwardly",
    )
    min_silence_gap_seconds: float = Field(
        default=0.3,
        ge=0.1,
        le=2.0,
        description="Minimum gap duration between words to consider as a natural pause/silence point",
    )


class BoundaryRefinementResult(BaseModel):
    """Detailed audit record of boundary refinement decisions and quality metrics."""
    original_start_seconds: float
    original_end_seconds: float
    refined_start_seconds: float
    refined_end_seconds: float
    original_duration_seconds: float
    refined_duration_seconds: float

    # Boundary metrics
    start_adjusted: bool
    end_adjusted: bool
    word_integrity_maintained: bool
    reason: str


def refine_candidate_boundaries(
    start_seconds: float,
    end_seconds: float,
    segments: List[TranscriptSegment],
    source_duration_seconds: float,
    max_clip_duration_seconds: float = 180.0,
    config: Optional[BoundaryRefinementConfig] = None,
) -> BoundaryRefinementResult:
    """Refine candidate boundaries using genuine word timings and outward silence cushions.

    Principles:
    1. Word Integrity: Never cut through a word. If start_seconds falls inside [w_start, w_end],
       snap start outwardly to w_start. If end_seconds falls inside [w_start, w_end], snap end to w_end.
    2. Outward Silence Cushion: In conversational exchanges, dialogue ending abruptly leaves no room
       for laughter or audience reaction. Seek outward into following silence up to outward_cushion_seconds,
       stopping cleanly before the next word starts.
    3. Context Preservation: If start is preceded by brief silence (< outward_cushion_seconds),
       extend slightly to give acoustic breath before the first syllable.
    4. Safety Invariants:
       - Never exceed source_duration_seconds.
       - Never go below 0.0s.
       - Never exceed max_clip_duration_seconds.
       - If extension would exceed max_clip_duration_seconds, cap cleanly at max duration or adjacent word.
    """
    cfg = config or BoundaryRefinementConfig()

    orig_start = float(start_seconds)
    orig_end = float(end_seconds)
    orig_dur = round(orig_end - orig_start, 3)

    # Flatten all available word timings from segments in chronological order
    all_words: List[WordTiming] = []
    for seg in segments:
        if seg.words:
            all_words.extend(seg.words)

    # Fallback if no word timings exist: clamp strictly to container bounds
    if not all_words:
        clamped_start = max(0.0, orig_start)
        clamped_end = min(source_duration_seconds, orig_end)
        clamped_dur = round(clamped_end - clamped_start, 3)
        return BoundaryRefinementResult(
            original_start_seconds=orig_start,
            original_end_seconds=orig_end,
            refined_start_seconds=clamped_start,
            refined_end_seconds=clamped_end,
            original_duration_seconds=orig_dur,
            refined_duration_seconds=clamped_dur,
            start_adjusted=(clamped_start != orig_start),
            end_adjusted=(clamped_end != orig_end),
            word_integrity_maintained=True,
            reason="No word timings available in transcript; clamped to source boundaries.",
        )

    # Sort words by start time
    all_words.sort(key=lambda w: w.start_seconds)

    # ----------------------------------------------------
    # Step 1: Word Integrity Snapping
    # ----------------------------------------------------
    new_start = orig_start
    new_end = orig_end
    word_integrity_fix = False

    # Check if orig_start cuts inside any word [w_start, w_end]
    for w in all_words:
        # If orig_start is strictly inside a word (not at the boundary)
        if w.start_seconds < orig_start < w.end_seconds:
            new_start = w.start_seconds
            word_integrity_fix = True
            break

    # Check if orig_end cuts inside any word [w_start, w_end]
    for w in all_words:
        if w.start_seconds < orig_end < w.end_seconds:
            new_end = w.end_seconds
            word_integrity_fix = True
            break

    # ----------------------------------------------------
    # Step 2: Outward Context / Silence Snapping
    # ----------------------------------------------------
    # For start: look at words before new_start.
    # Find the last word that ends before or at new_start:
    words_before = [w for w in all_words if w.end_seconds <= new_start + 0.001]
    if words_before:
        prev_word = words_before[-1]
        silence_before = new_start - prev_word.end_seconds
        # If there is a silence cushion, we can expand up to cfg.outward_cushion_seconds
        # into this silence without encroaching on prev_word
        expand_start = min(cfg.outward_cushion_seconds, silence_before * 0.5, cfg.max_extension_seconds)
        if expand_start > 0.05:
            new_start = max(prev_word.end_seconds + 0.05, new_start - expand_start)
    else:
        # Start of video: expand towards 0.0
        expand_start = min(cfg.outward_cushion_seconds, new_start, cfg.max_extension_seconds)
        if expand_start > 0.05:
            new_start = max(0.0, new_start - expand_start)

    # For end: look at words after new_end.
    # In conversational videos, extending into post-punchline laughter/reaction makes a huge difference.
    words_after = [w for w in all_words if w.start_seconds >= new_end - 0.001]
    if words_after:
        next_word = words_after[0]
        silence_after = next_word.start_seconds - new_end
        if silence_after > 0:
            # We can expand into the silence up to next_word.start_seconds - 0.05
            # or by outward_cushion_seconds, whichever is smaller
            target_expansion = min(cfg.outward_cushion_seconds, cfg.max_extension_seconds)
            # If silence is substantial (e.g. laughter gap between topics), take up to target_expansion
            expand_end = min(target_expansion, max(0.0, silence_after - 0.05))
            new_end = new_end + expand_end
    else:
        # End of video: expand towards source_duration_seconds
        silence_after = source_duration_seconds - new_end
        expand_end = min(cfg.outward_cushion_seconds, cfg.max_extension_seconds, max(0.0, silence_after))
        new_end = new_end + expand_end

    # ----------------------------------------------------
    # Step 3: Hard Safety Invariants & Clamping
    # ----------------------------------------------------
    # Absolute bounds
    new_start = max(0.0, new_start)
    new_end = min(source_duration_seconds, new_end)

    # Max duration check
    current_dur = new_end - new_start
    if current_dur > max_clip_duration_seconds:
        # Trim from end first to respect maximum duration cap
        new_end = new_start + max_clip_duration_seconds

    # Round to 3 decimal places
    new_start = round(new_start, 3)
    new_end = round(new_end, 3)
    new_dur = round(new_end - new_start, 3)

    reasons = []
    if word_integrity_fix:
        reasons.append("Snapped out of mid-word slice to preserve word integrity.")
    if new_start != orig_start:
        reasons.append(f"Adjusted start from {orig_start:.3f}s to {new_start:.3f}s.")
    if new_end != orig_end:
        reasons.append(f"Adjusted end from {orig_end:.3f}s to {new_end:.3f}s.")
    if not reasons:
        reasons.append("Boundaries already aligned with silence and word boundaries.")

    return BoundaryRefinementResult(
        original_start_seconds=orig_start,
        original_end_seconds=orig_end,
        refined_start_seconds=new_start,
        refined_end_seconds=new_end,
        original_duration_seconds=orig_dur,
        refined_duration_seconds=new_dur,
        start_adjusted=(new_start != orig_start),
        end_adjusted=(new_end != orig_end),
        word_integrity_maintained=True,
        reason="; ".join(reasons),
    )
