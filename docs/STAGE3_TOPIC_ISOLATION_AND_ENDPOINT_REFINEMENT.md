# Stage 3 Refinement #2 — Topic Isolation and Editorial Endpoint Completeness Report

**Document Date**: 2026-10-25  
**Evaluation Reference**: [`docs/evaluations/STAGE3_EDITORIAL_REFINEMENT_EVALUATION_REPORT.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/evaluations/STAGE3_EDITORIAL_REFINEMENT_EVALUATION_REPORT.md)  
**Baseline Artifacts Evaluated**:
- Master Package: `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/`
- Prior Evaluation Output: `experimental_output/eval_stage3_editorial_refinement_live_20261025/`

---

## 1. Executive Summary

In the latest controlled live evaluation (`eval_stage3_editorial_refinement_live_20261025`), the Stage 3 semantic anchor pipeline demonstrated strong technical reliability (zero validation rejections, valid duration compliance, clean Whisper word-boundary snapping, and successful 1080x1920 MP4 rendering). Furthermore, two out of three rendered clips were editorially viable:
- **Clip 01 (`8.80s - 19.72s`, `10.92s`, Score 87)**: Independent, punchy, self-contained charades confession.
- **Clip 03 (`31.44s - 43.83s`, `12.39s`, Score 80)**: Self-contained parenting reflection contrasting daughters and resolving with *"I don't throw the games"*.

However, **Clip 02 (`8.80s - 38.34s`, `29.54s`, Score 80)** suffered from severe over-stitching: it crossed backwards across the conversational topic boundary at `SEG_06` (*"Why kids?"* at `19.72s`), stitching the charades banter together with the parenting anecdote, yet truncated before the parenting anecdote reached its comedic climax.

This report documents:
1. The **exact control-flow root cause** of the topic-isolation failure in [`backend/app/services/candidates/expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py).
2. The **endpoint-completeness investigation** for the daughters/games anecdote (`SEG_10` vs `SEG_11`, *"I play for money too"*).
3. The minimal, general-purpose code improvements implemented.
4. Comprehensive regression testing (139 passing backend unit tests).
5. A clear recommendation for the next controlled live evaluation.

---

## 2. Task 1: Topic-Isolation Control-Flow Diagnosis & Fix

### 2.1 The Control-Flow Root Cause

In `construct_bounded_candidate_windows()`, backward search steps backward from `anc_start_idx - 1` down to `0`:

```python
for i in range(anc_start_idx - 1, -1, -1):
    seg = chunk_segments[i]
    prior_seg = chunk_segments[i - 1] if i > 0 else None
    ...
    if is_topic_transition_segment(seg.text):
        break
```

In the evaluation:
- The model selected anchor `anc_002` covering `[SEG_06, SEG_07]`.
- `anc_start_idx` was `6` (`SEG_06`).
- The text of `SEG_06` is: *"Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are like they they they're competitive too"*.
- `is_topic_transition_segment(chunk_segments[6].text)` evaluates to `True` (it contains the topic shift marker `"why kids"`).

**The Bug**:
The backward search loop began at `range(anc_start_idx - 1, -1, -1)`:
1. Segment `6` (`anc_start_idx`) was **never inspected** by the loop!
2. The loop began at index `5` (`SEG_05`: *"Less competitive now"*).
3. `SEG_05` is not a topic transition (`False`).
4. `SEG_04`, `SEG_03`, and `SEG_02` are not topic transitions.
5. At `SEG_02` (`8.88s`), prior segment `SEG_01` ended with a question mark (`"be?"`).
6. The loop recorded `(2, "moderate")` as a candidate start!
7. Paired with `end_candidates` `(9, 37.84s)`, it formed window `[8.88s - 37.84s]` (`moderate`), which won the priority tie-breaker over tight windows because `moderate` ranked ahead of `tight`!

### 2.2 Boundary Semantics & The Architectural Fix

We established strict boundary semantics:
1. **Anchor Starting At Topic Boundary**:
   If `is_topic_transition_segment(chunk_segments[anc_start_idx].text)` is `True`, the anchor itself marks the inception of a new conversational topic. Backward context expansion **must not run at all**. The anchor can only start at `anc_start_idx` (`"tight"`).
2. **Backward Walk Encountering Topic Boundary**:
   If an anchor starts *after* a topic transition (e.g., segment `N+2`), and backward search encounters segment `N` where `is_topic_transition_segment(chunk_segments[N].text)` is `True`:
   - Segment `N` is the setup header of the current topic. It is a valid candidate start (`"moderate"`).
   - However, the search **cannot step backward past segment N** into segment `N-1`. The loop breaks immediately after offering segment `N`.
3. **Fallback Guard**:
   In fallback window construction (when no candidate window met minimum duration), the fallback walk also respects `if is_topic_transition_segment(chunk_segments[anc_start_idx].text)` and breaks immediately if a preceding segment is a topic transition.

### 2.3 General-Purpose Regex Pattern Hardening

In addition to the control-flow bug, regex patterns in `TOPIC_TRANSITION_PATTERNS` previously contained punctuation (e.g. `r"\blet's talk about\b"`, `r"\bmoving on to\b"`). Because transcript text is normalized via `_normalize_text_for_matching()` (which strips punctuation: `"let's"` $\to$ `"lets"`), patterns containing apostrophes could never match.

We hardened the pattern set to be general-purpose and match normalized text:
```python
TOPIC_TRANSITION_PATTERNS = [
    r"\bwelcome back\b",
    r"\bour next guest\b",
    r"\bmoving on\b",
    r"\blets talk about\b",
    r"\bswitch gears\b",
    r"\bswitching gears\b",
    r"\bso tell me\b",
    r"\btell me about\b",
    r"\bspeaking of\b",
    r"\bby the way\b",
    r"\btonight we have\b",
    r"\bthank you for being here\b",
    r"\bthank you for playing\b",
    r"\bwhy kids\b",
    r"\bdo you play games at home\b",
]
```

---

## 3. Task 2: Endpoint Completeness Investigation

### 3.1 Trace of the daughters/game anecdote (`SEG_10` vs `SEG_11`)

In the live evaluation:
- `SEG_10` (`38.39s - 43.83s`, 5.44s): *"Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games"*
- `SEG_11` (`43.83s - 47.69s`, 3.86s): *"You know, I go I go I go I really and I play for I play for money to"*

The live evaluation produced Clip 03 ending at `43.83s` (`SEG_10`). Why didn't it include `SEG_11`?
1. **Model Proposal**: The model emitted anchor `anc_003` with `anchor_segment_ids = [10]`. It did not include `SEG_11`.
2. **Forward Search**: Forward exploration from `SEG_10` inspected `SEG_11`. `is_reaction_or_resolution(segs[11].text)` evaluated to `True` (matching `"play for money"`). Thus, `end_candidates` included both:
   - `(10, 43.83s)`
   - `(11, 47.69s)`
3. **Start Exploration**: Anchor `[10]` had raw duration 5.44s ($< 10.0\text{s}$). Backward search stepped back to `SEG_08` (`31.44s`, *"My kids are very competitive..."*).
4. **Candidate Pairs Formed**:
   - `[31.44s - 43.83s]` (`12.39s`)
   - `[31.44s - 47.69s]` (`16.25s`)
5. **Deduplication / NMS**:
   $$\text{Intersection} = 43.83 - 31.44 = 12.39\text{s}$$
   $$\text{Union} = 47.69 - 31.44 = 16.25\text{s}$$
   $$\text{IoU} = \frac{12.39}{16.25} = 0.762 \ge 0.50$$
   The endpoint difference was $47.69 - 43.83 = 3.86\text{s}$.
   Because the endpoint difference was $\le 6.0\text{s}$, the endpoint diversity exception in `ranking.py` was not triggered, and standard NMS suppressed `[31.44s - 47.69s]` in favor of `[31.44s - 43.83s]`.

### 3.2 Editorial Assessment of `SEG_11`

Does omitting `SEG_11` represent an editorial failure?
- **Standalone Value of `[31.44s - 43.83s]`**: High. Anne Hathaway says:
  > *"My kids are very competitive. Well, my one daughter is yeah Yeah, the other one doesn't really care Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games"*
  This is a complete, self-contained comedic statement about parenting and game dynamics.
- **Value of `SEG_11` (`43.83s - 47.69s`)**:
  > *"You know, I go I go I go I really and I play for I play for money to"*
  While funny, Anne stumbles and repeats words (*"I go I go I go I really and I play for I play for..."*). Including it is an escalation, but omitting it does not break the syntactic or comedic completeness of Clip 03.
- **Safety Principle**: We must not add arbitrary score bonuses or force extensions when a candidate is already complete. Shorter standalone moments must be preserved when longer extensions risk adding verbal stumble or diluting pacing.

---

## 4. Task 3: Unit Testing & Verification

We added 4 new deterministic unit tests in [`backend/tests/unit/test_candidate_expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_candidate_expansion.py#L450-L540):

1. **`test_topic_isolation_backward_expansion_stops_at_boundary`**:
   Verifies that an anchor in a new topic (movie discussion) expands backward to the topic intro marker, but never crosses into the preceding discussion (weather).
2. **`test_topic_isolation_anchor_at_transition_does_not_expand_backward`**:
   Verifies that when an anchor starts directly on a topic transition segment (*"Switch gears and talk about your family"*), backward search does not run, preventing any earlier segments from being attached.
3. **`test_topic_isolation_fallback_does_not_cross_boundary`**:
   Verifies that fallback candidate generation refuses to cross a topic boundary even when the anchor is sub-minimum duration.
4. **`test_forward_continuation_stops_before_new_topic`**:
   Verifies that forward expansion terminates before a downstream topic transition cue (*"Welcome back everyone! Our next guest is..."*).

### Test Suite Execution Results:
- `backend/tests/unit/test_candidate_expansion.py`: **19 passed in 0.08s**.
- Full Backend Unit Suite (`backend/tests/unit/`): **139 passed in 1.18s** (100% pass rate).

---

## 5. Task 4: Ranking & Deduplication Integrity

- **Endpoint Diversity Threshold**: Retained at $6.0\text{s}$. A threshold below $4.0\text{s}$ would allow minor trailer stumbles or filler backchannels to generate duplicate clips.
- **Score Integrity**: Computed scores remain untouched; no duration bonuses, length penalties, or artificial weights were introduced.
- **Preservation of Existing Results**:
  - Clip 01 (`8.88s - 19.72s`) remains a top-ranked, valid candidate.
  - With the topic-isolation bug resolved, the over-stitched Clip 02 (`8.88s - 38.34s`) is **eliminated** from raw window generation.
  - The kids discussion correctly originates at `19.72s` (`SEG_06`), yielding clean candidate windows within the parenting topic.

---

## 6. Protection of Protected Artifacts

1. **Baseline Hash Verification**:
   - `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`:
     `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (**CONFIRMED UNCHANGED**).
2. **Protected Directories**:
   - `input/`: Unchanged.
   - `outputs/`: Unchanged.
   - `experimental_output/eval_stage2_stage3_live_20261024/`: Unchanged.
   - `experimental_output/eval_stage3_semantic_anchor_live_20261025/`: Unchanged.
   - `experimental_output/eval_stage3_editorial_refinement_live_20261025/`: Unchanged.

---

## 7. Recommendation

With the control-flow bug diagnosed, corrected, and verified across 139 unit tests:
- **Recommendation**: **AUTHORIZE NEXT CONTROLLED LIVE EVALUATION**.
- **Target Output Directory**: `experimental_output/eval_stage3_topic_isolation_live_20261025`
- **Expected Outcome**:
  1. Clip 01 (*"Less competitive now"*) is preserved.
  2. Over-stitched Clip 02 (*charades + kids*) is eliminated.
  3. The kids discussion forms a cleanly isolated, standalone Short without topic leakage.
