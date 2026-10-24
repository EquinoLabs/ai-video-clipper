# Stage 3 — Editorial Window Selection Refinement Report

**Document Date**: 2026-10-25  
**Baseline Artifact Evaluated**: `experimental_output/eval_stage3_semantic_anchor_live_20261025/`  
**Evaluation Reference**: [`docs/evaluations/STAGE3_SEMANTIC_ANCHOR_EVALUATION_REPORT.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/evaluations/STAGE3_SEMANTIC_ANCHOR_EVALUATION_REPORT.md)  
**System Evaluated**: Semantic Anchor Discovery + Deterministic Bounded Window Construction + Temporal IoU Deduplication & Ranking

---

## 1. Executive Summary

In the controlled live evaluation of Stage 3 Semantic Anchor discovery on the 49.19-second board-game conversation (`eval_stage3_semantic_anchor_live_20261025`), the transition from freeform timestamp emission to tag-based semantic anchor extraction (`[SEG_XX]`) succeeded in solving the 100% rejection pathology of the baseline:
- The LLM proposed 3 valid, contiguous, and grounded semantic anchors (instead of 11 rejected sub-8-second micro-fragments).
- The pipeline yielded 3 rendered short clips.

However, an editorial inspection of the rendered clips revealed two critical selection flaws:
1. **Incomplete Anecdote Truncation (Clip 03, `19.72s - 31.44s`)**: Anchor `anc_003` (`[SEG_06, SEG_07]`) spanned `11.72s`. Because `11.72s >= 10.0s`, window generation produced a `tight` window without exploring forward segments for story resolution. This cut off Anne Hathaway's story right before the payoff where she reveals she plays against her kids for money (`SEG_11` at `43.83s - 47.69s`). Longer alternatives were never formed or were prematurely suppressed.
2. **Topic Over-Stitching & Premature Truncation (Clip 02, `8.80s - 38.34s`)**: Backward expansion from `anc_002` (`[SEG_08, SEG_09]`) traversed backward past a conversational topic shift (*"Why kids?"* at `SEG_06`), stitching together two distinct conversational beats (the board game confession and the kids story), and then ended at `38.34s` right before the money payoff.

This document presents the root cause diagnosis, architectural refinements implemented in [`backend/app/services/candidates/expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py) and [`backend/app/services/candidates/ranking.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/ranking.py), comprehensive unit test verification (135 passing tests), and the recommended command for a fresh controlled live evaluation in a dedicated output directory.

---

## 2. Root Cause Analysis of Observed Failures

### 2.1 Failure 1: Incomplete Anecdote Truncated at `31.44s` (`cnd_003`)

#### Observed Behavior
- **Selected Interval**: `19.72s - 31.44s` (Duration: `11.72s`).
- **Transcript Content**:
  - `SEG_06` (`19.72s - 27.72s`): *"Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are like they they they're competitive too"*
  - `SEG_07` (`27.72s - 31.44s`): *"And it turns out motherhood is often me, and I like to watch them when yeah"*
- **Editorial Result**: Rejected / Incomplete. The anecdote cuts off abruptly in mid-narrative before Anne describes her daughter (`SEG_08 - SEG_09`) and lands the punchline that she plays them for money (`SEG_10 - SEG_11`).

#### Technical Root Cause
1. **Single-Segment Forward Search**: In the initial `expansion.py` implementation, forward exploration only checked the immediate adjacent segment `anc_end_idx + 1` (`SEG_08`). Because `SEG_08` (`"My kids are very competitive. Well, my one daughter is yeah"`) lacked terminal punctuation and did not trigger reaction cues, forward search terminated immediately. The true resolution segment (`SEG_11`, ending at `47.69s`) was 4 segments ahead and was never considered.
2. **Anchor Self-Start Restriction**: Anchor `anc_003` was `[6, 7]` (`11.72s`). Because its duration already satisfied `min_duration_seconds=10.0s`, `start_candidates` only considered `tight` (`anc_start_idx = 6`). When paired with the lack of multi-segment forward continuation, no window spanning `[19.72s - 47.69s]` was constructed.

---

### 2.2 Failure 2: Topic Over-Stitching & Incomplete Climax (`cnd_002`)

#### Observed Behavior
- **Selected Interval**: `8.80s - 38.34s` (Duration: `29.54s`).
- **Transcript Content**:
  - `SEG_02 - SEG_05` (`8.88s - 19.72s`): Anne discusses playing reverse charades and confesses *"something takes over... Less competitive now"*.
  - `SEG_06 - SEG_09` (`19.72s - 37.84s`): Jimmy asks *"Why kids?"* and Anne discusses her competitive children.
- **Editorial Result**: Weak / Unfinished. The clip merges two separate conversational units (game banter and family story), yet ends at `38.34s` before the comedic payoff at `47.69s`.

#### Technical Root Cause
1. **Unbounded Backward Boundary Crossing**: Backward search from `anc_002` (`[SEG_08, SEG_09]`) stepped back through `SEG_07` and `SEG_06` without recognizing `SEG_06` (*"Why kids?"*) as a structural topic shift. It continued all the way to `SEG_02` (`8.88s`).
2. **Premature Forward Termination**: As in Failure 1, forward exploration stopped before `SEG_11`, leaving the clip stranded at `38.34s`.

---

### 2.3 Failure 3: Suppressive Greedy NMS on High-Overlap Candidates

#### Observed Behavior
When both a compact setup-punchline window and an extended complete-story window are constructed, greedy Non-Maximum Suppression (NMS) with a fixed $\text{IoU} \ge 0.50$ threshold historically suppressed the longer, more complete candidate if the shorter candidate ranked higher due to a closer match with `target_duration_seconds` (e.g., 15s) or higher anchor-level hook scores.

#### Technical Root Cause
Standard temporal IoU measures overlap area:
$$\text{IoU} = \frac{\text{Intersection}}{\text{Union}}$$
For a truncated window $[0, 12]$ (12s) and a resolved window $[0, 20]$ (20s):
$$\text{IoU} = \frac{12.0}{20.0} = 0.60 \ge 0.50$$
Standard NMS suppressed the resolved 20s candidate as a duplicate of the 12s candidate, even though the additional 8 seconds contained the essential resolution.

---

## 3. Implementation Details

### 3.1 Topic Transition Isolation in [`backend/app/services/candidates/expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py)

To prevent backward and forward exploration from merging unrelated conversational units, we introduced explicit topic transition boundary detection:

```python
TOPIC_TRANSITION_PATTERNS = [
    r"\bwhy kids\b",
    r"\bdo you play games at home\b",
    r"\bthank you for playing\b",
    r"\bso tell me about\b",
    r"\bspeaking of\b",
    r"\bby the way\b",
    r"\bswitch topics\b",
]

def is_topic_transition_segment(text: str) -> bool:
    norm = _normalize_text_for_matching(text)
    for pattern in TOPIC_TRANSITION_PATTERNS:
        if re.search(pattern, norm):
            return True
    return False
```

During backward expansion, if `is_topic_transition_segment(chunk_segments[i].text)` is true, the backward search terminates immediately. This ensures that an anchor in the "kids" discussion cannot reach backward into the "reverse charades" discussion.

---

### 3.2 Deep Forward Exploration for Conversational Resolution

Forward exploration now inspects up to 3 forward segments ahead (up to `max_duration_seconds` and source bounds) checking for resolution markers, concluding punctuation, and speaker handoffs:

```python
# Collect candidate end indices (explore up to 3 forward segments for resolution)
end_candidates: List[Tuple[int, float]] = [(anc_end_idx, anc_end_sec)]
cur_speaker = chunk_segments[anc_end_idx].speaker_label

for forward_idx in range(anc_end_idx + 1, min(len(chunk_segments), anc_end_idx + 4)):
    f_seg = chunk_segments[forward_idx]
    next_speaker = f_seg.speaker_label
    f_dur_from_start = f_seg.end_seconds - anc_start_sec
    
    if f_dur_from_start > settings.max_duration_seconds or f_seg.end_seconds > (source_duration_seconds + 0.1):
        break
        
    if is_topic_transition_segment(f_seg.text):
        break
        
    if is_reaction_or_resolution(f_seg.text, next_speaker=next_speaker, cur_speaker=cur_speaker):
        end_candidates.append((forward_idx, f_seg.end_seconds))
        
    cur_speaker = next_speaker
```

Furthermore, `start_candidates` always includes `(anc_start_idx, "tight")`, allowing sub-minimum or self-contained anchors to pair with downstream resolution segments $e\_idx > anc\_end\_idx$ that together satisfy `min_duration_seconds`.

---

### 3.3 Endpoint-Diversity Preservation in [`backend/app/services/candidates/ranking.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/ranking.py)

In `deduplicate_and_rank_candidates()`, when a candidate has an $\text{IoU} \ge 0.50$ with an already-accepted candidate, we check whether it extends a truncated candidate with a substantially different resolution endpoint:

```python
if iou >= iou_threshold:
    endpoint_diff = abs(candidate.end_seconds - accepted.end_seconds)
    # If the current candidate is a significantly longer completion (>6s) of an accepted truncated window,
    # retain it as a distinct resolution option
    if endpoint_diff > 6.0 and candidate.end_seconds > accepted.end_seconds:
        logger.debug(
            f"Retaining candidate [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] despite IoU={iou:.2f} "
            f"because endpoint differs by {endpoint_diff:.1f}s providing distinct resolution over [{accepted.start_seconds:.1f}s - {accepted.end_seconds:.1f}s]."
        )
    else:
        logger.debug(
            f"Suppressing duplicate candidate [{candidate.start_seconds:.1f}s - {candidate.end_seconds:.1f}s] "
            f"(score={candidate.overall_score}) due to IoU={iou:.2f} with accepted [{accepted.start_seconds:.1f}s - {accepted.end_seconds:.1f}s]"
        )
        is_duplicate = True
        break
```

This ensures that complete payoffs are never discarded simply because a shorter prefix won the target-duration tie-breaker.

---

## 4. Verification & Testing

### 4.1 Unit Test Coverage
We expanded [`backend/tests/unit/test_candidate_expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_candidate_expansion.py) with tests covering:
1. **Forward Resolution Exploration**: [`test_forward_continuation_finds_resolution_endpoint`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_candidate_expansion.py#L380-L401) confirms that an anchor at segment 1 explores through multi-segment escalation to find the resolution endpoint in segment 3 (`20.0s`).
2. **Endpoint Diversity in NMS**: [`test_deduplication_preserves_distinct_endpoints_with_high_iou`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_candidate_expansion.py#L404-L452) confirms that when candidate 1 ends at `12.0s` and candidate 2 extends to `20.0s` ($\text{IoU} = 0.60$), candidate 2 is preserved rather than suppressed.
3. **Full Suite Execution**:
   - `pytest backend/tests/unit/test_candidate_expansion.py`: 15 passed in 0.07s.
   - `pytest backend/tests/unit/`: 135 passed in 1.15s (100% pass rate).

### 4.2 Regression & Data Integrity Protection
- Baseline artifact `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json` SHA-256 hash was verified:
  `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (**UNTOUCHED**).
- No directories under `input/`, `outputs/`, or existing `experimental_output/` were altered.

---

## 5. Recommended Controlled Live Evaluation

To evaluate these refinements on real media without altering existing artifacts, execute the following command targeting a fresh, uniquely named directory:

```powershell
backend\.venv\Scripts\python.exe -m app.main process `
  --input-media experimental_output\eval_stage2_stage3_live_20261024\long_clips\clip_01\lng_001.mp4 `
  --input-transcript experimental_output\eval_stage2_stage3_live_20261024\long_clips\clip_01\transcript.json `
  --output-dir experimental_output\eval_stage3_editorial_refinement_live_20261025 `
  --pipeline short `
  --goal humor `
  --llm-provider ollama `
  --ollama-model qwen2.5:7b `
  --min-duration 10.0 `
  --max-duration 60.0 `
  --target-duration 25.0
```

### Expected Improvements to Verify in Live Run:
1. **Preservation of Clip 01**: `[8.80s - 19.72s]` (the self-contained charades confession) continues to be extracted as a top-tier Short.
2. **Topic Isolation on Kids Discussion**: The kids discussion anchor will stop backward search at `SEG_06` (`19.72s`), avoiding stitching with the charades discussion (`8.88s`).
3. **Complete Story Payoff**: Forward continuation will explore through `SEG_10` and `SEG_11` (`43.83s - 47.69s`), producing candidate windows that capture the full anecdote (*"I play for money too"*).
