# Stage 3 — Short Discovery Implementation Refinement (Revised Specification)

**Author:** Antigravity AI  
**Date:** 2026-10-25  
**Status:** SPECIFICATION COMPLETE (Read-Only Design Refinement)  
**Target:** AI Video Clipper — Stage 3 Standalone Short-Clip Pipeline  
**Companion Documents:**
- [`docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md)
- [`docs/STAGE3_SHORT_DISCOVERY_PROMPT_DIAGNOSIS.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_PROMPT_DIAGNOSIS.md)

---

## 1. Executive Summary & Core Architectural Refinement

This document provides the final, implementation-ready technical specification for the **Semantic Anchor + Bounded Candidate-Window Construction** architecture (Approach A).

In our Stage 3 live evaluation (`eval_stage2_stage3_live_20261024`), Ollama `qwen2.5:7b` analyzed a 49.19-second board-game conversation and proposed 11 candidates ranging from 1.88s to 8.00s. All 11 were rejected below the 10.0s minimum threshold. The prompt diagnosis confirmed that the LLM copied segment boundary timestamps flanking isolated quotes (e.g. `"I play for money to"`).

### Core Refinements Resolved in this Specification:
1. **Bounded Window Generation with Robust Fallback**:
   Replaces open-ended loops with a deterministic algorithm producing at most **3 candidate windows per anchor** (Tight, Moderate, Broad). Fallback behavior is explicitly defined when structural candidates exist but fail duration or container limits: search terminates gracefully, and the anchor is rejected without synthetic padding.
2. **Structural Cues Treated as Heuristics (Not Proof)**:
   Punctuation marks, speaker turn shifts, and silence gaps are explicitly specified and treated as imperfect structural indicators rather than mathematical proofs of semantic completeness.
3. **Anchor vs. Window Scoring Transparency**:
   Documents the exact scoring relationship: anchor scores evaluate the core moment's voltage (`hook_strength`, `goal_specific_impact`, `goal_relevance`), while window-level completeness and pacing are treated as inherited proxy metrics in Stage 3 to avoid an expensive second LLM call.
4. **Resolution of Duration Validation & Refinement Order**:
   Establishes the authoritative lifecycle: meaningful candidate-window construction occurs *first* ($\ge 10.0\text{s}$ raw segment duration requirement). Word-timestamp boundary refinement *never* artificially inflates sub-minimum fragments to pass duration checks; it only adds acoustic breath/cushion to already valid candidates.
5. **Rigorous Identifier & Grounding Contract**:
   Specifies the exact translation between prompt-visible `[SEG_XX]` tags and chunk-local / transcript-global indices. Validates both `transcript_excerpt` and `evidence` quotes against transcript ground truth.
6. **Zero Accepted Shorts Invariant**:
   If an anchor cannot be expanded into a standalone window without crossing topic boundaries or violating duration constraints, it is rejected. Zero accepted Shorts remains a valid, cleanly supported outcome.

---

## 2. Confirmed Implementation Contracts & Call Sites

We inspected the actual implementation files, schemas, and test fixtures:

| Component / Function | Location | Current Signature / Contract | Refinement Implementation Plan |
|---|---|---|---|
| `LLMCandidateEvaluation` | `app/api/v1/schemas/candidates.py:189` | `start_seconds: float`, `end_seconds: float`, `hook: str`, `transcript_excerpt: str`, `score_dimensions: ScoreBreakdown`, `rationale: str`, `evidence: List[EvidenceItem]`, `confidence_label: ConfidenceLabel` | Introduce sibling schema `LLMAnchorEvaluation` where `start/end_seconds` are replaced with `anchor_segment_ids: List[int]` and `anchor_type: str`. |
| `ScoreBreakdown` | `app/api/v1/schemas/candidates.py:64` | 8 dimensions (`0.0` to `5.0`): `hook_strength`, `completeness_coherence`, `standalone_understandability`, `goal_relevance`, `goal_specific_impact`, `specificity_insight`, `pacing_conciseness`, `ending_quality`. | **Unchanged**. Inherited directly from anchor evaluation. |
| `GenerationSettings` | `app/api/v1/schemas/candidates.py:81` | `min_duration_seconds: float = 10.0`, `target_duration_seconds: float = 30.0`, `max_duration_seconds: float = 60.0`, `candidate_pool_target: int = 10`, `display_limit: int = 10`. | **Unchanged**. Governs window construction bounds. |
| `validate_candidate_against_transcript()` | `app/services/candidates/validation.py:116` | Takes candidate, `segments`, `settings`, `source_duration_seconds`. Returns `CandidateValidationResult(is_valid, status, reasons, reason_codes)`. | Validates resolved candidate windows against duration, media bounds, and verbatim evidence quotes. |
| `refine_candidate_boundaries()` | `app/services/candidates/boundaries.py:50` | Snaps start/end to word timings and applies outward silence cushion up to `outward_cushion_seconds` (1.0s). | **Unchanged**. Operates strictly on validated candidate windows. |
| `deduplicate_and_rank_candidates()` | `app/services/candidates/ranking.py:45` | Validates evaluations, computes `calculate_overall_score()`, sorts by `(-overall_score, target_diff, start_seconds)`, and applies greedy IoU NMS (`iou_threshold=0.50`). | Receives fully constructed, grounded `CandidateListItem` models. NMS resolves overlapping windows cleanly. |
| `run_short_clip_pipeline()` | `app/services/candidates/short_pipeline.py:40` | Orchestrates chunking, LLM invocation, ranking, boundary refinement, revalidation, writing `short_candidates.json`, and rendering. | Calls `expand_anchors_to_candidates()` between raw LLM output and ranking. |

---

## 3. Grounding, Identifier Translation & Schema Specifications

### 3.1 Identifier Mapping: Prompt-Visible `[SEG_XX]` to Transcript Segments
When processing long transcripts, transcripts may be chunked via [`chunk_transcript()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/chunking.py#L33).
1. **Prompt Display Format**:
   Segments supplied to the LLM are rendered with zero-indexed string tags:
   ```text
   [SEG_00] (speaker: Jimmy) Why kids? Yeah, yeah, maybe being competitive is genetic...
   [SEG_01] (speaker: Jimmy) And it turns out motherhood is often me...
   [SEG_02] (speaker: Anne) My kids are very competitive. Well, my one daughter is yeah...
   [SEG_05] (speaker: Anne) You know, I go I go I really and I play for I play for money to
   ```
2. **Chunk-Local vs. Transcript-Global Indexing**:
   - The LLM always operates on the list of segments provided in the immediate chunk context. To avoid LLM arithmetic errors across offsets, **the prompt uses chunk-local indices `0, 1, ..., M-1`** corresponding to `chunk.segments[0 ... M-1]`.
   - When the LLM returns `anchor_segment_ids: [4, 5]`, the backend verifies:
     $0 \le \text{ID} < \text{len}(chunk.segments)$.
   - The backend maps chunk-local index $k$ to the transcript-global segment:
     $$\text{global\_seg} = chunk.segments[k]$$
   - All subsequent window construction and timestamp lookups use the resolved `TranscriptSegment` objects directly.

### 3.2 LLM Output Schema: `LLMAnchorEvaluation`
```python
class AnchorType(str, Enum):
    PUNCHLINE = "punchline"
    COMEDIC_BANTER = "comedic_banter"
    STORY_CLIMAX = "story_climax"
    PROVOCATIVE_HOOK = "provocative_hook"
    INSIGHT = "insight"
    EMOTIONAL_REACTION = "emotional_reaction"


class LLMAnchorEvaluation(BaseModel):
    """Semantic anchor emitted by the LLM during short discovery."""
    anchor_id: str = Field(..., description="Unique anchor ID, e.g. 'anc_001'")
    anchor_segment_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="Contiguous list of 1 to 4 chunk-local segment indices containing the anchor",
    )
    anchor_type: AnchorType = Field(
        ..., description="Categorical classification of the semantic anchor"
    )
    hook: str = Field(
        ..., min_length=5, max_length=150, description="Brief explanation of the hook or punchline"
    )
    transcript_excerpt: str = Field(
        ..., min_length=5, description="Verbatim quote of the anchor core line"
    )
    score_dimensions: ScoreBreakdown = Field(
        ..., description="Standard 8-dimension ratings (0.0 to 5.0) evaluating anchor quality"
    )
    rationale: str = Field(
        ..., min_length=10, description="Editorial rationale explaining why this moment is compelling"
    )
    evidence: List[EvidenceItem] = Field(
        ..., min_length=1, description="Verbatim quotes from transcript grounding the anchor"
    )
    confidence_label: ConfidenceLabel = Field(default=ConfidenceLabel.HIGH)
```

### 3.3 Authoritative Validation Rules for Anchors
Before window construction begins, each anchor is validated:
1. **Segment ID Validity**: Every ID in `anchor_segment_ids` must exist within $[0, \text{len}(chunk.segments) - 1]$. If any ID is out of range, the anchor is rejected (`UNKNOWN_SEGMENT_ID`).
2. **Contiguity Invariant**: `anchor_segment_ids` must form a strictly contiguous sequence of integers (e.g., $[4, 5]$ is valid; $[3, 5]$ is rejected as `DISCONTIGUOUS_ANCHOR`).
3. **`transcript_excerpt` Grounding**: The text in `transcript_excerpt` must be present verbatim (case- and punctuation-normalized) within the transcript text of the specified `anchor_segment_ids`. If not found, the anchor is rejected (`EXCERPT_NOT_GROUNDED`).
4. **`evidence` Grounding**: Each item in `evidence` must match verbatim in the chunk transcript and must have non-zero temporal overlap with the anchor segment span. If ungrounded, the anchor is rejected (`EVIDENCE_NOT_GROUNDED`).
5. **Duplicate Anchor Suppression**: If multiple anchors share identical segment spans and anchor types, only the anchor with the higher `goal_specific_impact` score is retained.

---

## 4. Bounded Candidate-Window Generation Algorithm

### 4.1 Structural Cues as Imperfect Indicators
Structural markers in transcripts provide helpful layout hints, but they are **imperfect heuristics, not proofs of narrative completeness**:
- **Sentence Punctuation**: Whisper often places periods at acoustic pauses rather than true syntactic sentence boundaries, or conversely transcribes long run-on sentences without punctuation.
- **Speaker Turns**: A speaker change indicates a new conversational contribution, but may be a simple backchannel (*"yeah"*, *"right"*) rather than a topic transition.
- **Silence Gaps**: Acoustic pauses $\ge 0.35\text{s}$ frequently indicate conversational boundaries, but can also occur during hesitation or dramatic pauses.

Therefore, window generation uses these structural cues to propose candidate boundaries, while duration limits and editorial ranking govern candidate selection.

### 4.2 Candidate Start & End Point Identification
For an anchor spanning chunk segments $[S_{\text{start}}, S_{\text{end}}]$:

1. **Candidate Starts ($B_{\text{start}}$)**:
   - $B_0$ (Self): If anchor duration $\ge \text{settings.min\_duration\_seconds}$ (10.0s), include $S_{\text{start}}$ as a candidate start ("Tight").
   - $B_{\text{sentence}}$: Step backward looking for a segment whose text starts with a capitalized word immediately following terminal punctuation (`.`, `!`, `?`) in the prior segment.
   - $B_{\text{turn}}$: Step backward looking for a speaker change (where `speaker_label` differs from the anchor speaker, if available) or conversational setup phrase (e.g. *"Why kids?", "Do you play games at home?"*).
   - *Lookback Safety Bound*: Backward search never looks back more than $35.0$ seconds prior to $S_{\text{start}}$.
   - *Topic Boundary Guard*: If a segment contains a host transition phrase (*"Our next guest...", "Welcome back..."*) or an explicit topic pivot, search stops immediately at that segment.
2. **Candidate Ends ($F_{\text{end}}$)**:
   - $F_0$ (Self): The anchor end segment $S_{\text{end}}$.
   - $F_{\text{reaction}}$: The segment immediately following $S_{\text{end}}$ ($S_{\text{end}} + 1$), if it provides conversational resolution or audience reaction within container bounds.
   - *Container Safety Bound*: $F_{\text{end}}$ cannot exceed the chunk or source duration.

### 4.3 Fallback & Window Filtering Pseudocode
```python
def construct_bounded_candidate_windows(
    anchor: LLMAnchorEvaluation,
    segments: List[TranscriptSegment],
    settings: GenerationSettings,
    source_duration_seconds: float,
) -> List[Tuple[float, float, str]]:
    """Generate at most 3 distinct, bounded candidate windows for a semantic anchor.
    Returns: List of (start_seconds, end_seconds, window_type)
    """
    anc_start_idx = min(anchor.anchor_segment_ids)
    anc_end_idx = max(anchor.anchor_segment_ids)
    
    anc_start_sec = segments[anc_start_idx].start_seconds
    anc_end_sec = segments[anc_end_idx].end_seconds
    anc_dur = anc_end_sec - anc_start_sec

    # 1. Collect candidate start indices
    start_candidates = []
    
    # B0: Tight (anchor itself, if it meets minimum duration)
    if anc_dur >= settings.min_duration_seconds:
        start_candidates.append((anc_start_idx, "tight"))
        
    # Search backwards for B_sentence and B_turn within lookback budget (35s)
    lookback_budget_sec = 35.0
    found_sentence = False
    found_turn = False
    
    for i in range(anc_start_idx - 1, -1, -1):
        seg = segments[i]
        prior_seg = segments[i - 1] if i > 0 else None
        seg_dur_span = anc_end_sec - seg.start_seconds
        
        # Guard: Exceeded max duration or lookback budget
        if seg_dur_span > settings.max_duration_seconds or (anc_start_sec - seg.start_seconds) > lookback_budget_sec:
            break
            
        # Guard: Topic shift detected
        if is_topic_transition_segment(seg.text):
            break
            
        # Check for sentence boundary (prior segment ends in terminal punctuation)
        if prior_seg and prior_seg.text.rstrip().endswith((".", "!", "?")):
            if not found_sentence:
                start_candidates.append((i, "moderate"))
                found_sentence = True
                continue
                
        # Check for speaker turn change (if speaker labels available)
        if seg.speaker_label and seg.speaker_label != segments[anc_start_idx].speaker_label:
            if not found_turn:
                start_candidates.append((i, "broad"))
                found_turn = True
                continue

    # 2. Collect candidate end indices
    end_candidates = [(anc_end_idx, anc_end_sec)]
    if anc_end_idx + 1 < len(segments):
        next_seg = segments[anc_end_idx + 1]
        if (next_seg.end_seconds - anc_start_sec) <= settings.max_duration_seconds:
            if is_reaction_or_resolution(next_seg.text):
                end_candidates.append((anc_end_idx + 1, next_seg.end_seconds))

    # 3. Form candidate pairs and filter strictly
    valid_windows = []
    seen_intervals = set()
    
    for s_idx, w_type in start_candidates:
        w_start = segments[s_idx].start_seconds
        for e_idx, w_end in end_candidates:
            w_dur = round(w_end - w_start, 3)
            if settings.min_duration_seconds <= w_dur <= settings.max_duration_seconds:
                interval_key = (round(w_start, 2), round(w_end, 2))
                if interval_key not in seen_intervals:
                    seen_intervals.add(interval_key)
                    valid_windows.append((w_start, w_end, w_type))

    # 4. Fallback Handling: When start_candidates existed but all pairs failed validation
    # (e.g. all formed windows were <10s or >60s, or start_candidates was empty because anchor <10s)
    if not valid_windows and anc_dur < settings.min_duration_seconds:
        # Search backwards segment-by-segment for the earliest segment satisfying min_duration
        for i in range(anc_start_idx - 1, -1, -1):
            w_start = segments[i].start_seconds
            w_dur = round(anc_end_sec - w_start, 3)
            
            if (anc_start_sec - w_start) > lookback_budget_sec:
                break
            if w_dur > settings.max_duration_seconds:
                break
            if is_topic_transition_segment(segments[i].text):
                break
                
            if w_dur >= settings.min_duration_seconds:
                interval_key = (round(w_start, 2), round(anc_end_sec, 2))
                if interval_key not in seen_intervals:
                    seen_intervals.add(interval_key)
                    valid_windows.append((w_start, anc_end_sec, "fallback_moderate"))
                break  # Exactly one fallback window to prevent duplicate generation

    # 5. Strict Cardinality Cap: Keep at most 3 non-duplicate windows
    # Sort windows by proximity to target duration (30s)
    valid_windows.sort(key=lambda w: abs((w[1] - w[0]) - settings.target_duration_seconds))
    return valid_windows[:3]
```

---

## 5. Candidate Scoring: Anchor vs. Window Relationship

### 5.1 The Scoring Semantic Gap
The LLM evaluates the *anchor* ($1\text{s}–8\text{s}$), while deterministic expansion produces an expanded *candidate window* ($15\text{s}–45\text{s}$).

We explicitly document the implications of this relationship:
- **Directly Applicable Dimensions**: `hook_strength`, `goal_relevance`, `goal_specific_impact`, and `specificity_insight` accurately reflect the editorial voltage of the underlying moment.
- **Proxy Dimensions**: `completeness_coherence`, `standalone_understandability`, `pacing_conciseness`, and `ending_quality` as rated by the LLM reflect the anchor's local punchiness. In Stage 3, the expanded window inherits these ratings directly as proxy metrics.

### 5.2 Why We Do Not Add a Second LLM Call in Stage 3
Introducing a second LLM pass solely to re-rate the expanded window would double processing time (adding ~35s per candidate) and introduce new failure modes (model hallucinating timestamps or dropping valid windows).

Instead, Stage 3 adopts the minimal, robust approach:
1. The expanded candidate window inherits the anchor's `ScoreBreakdown`.
2. The backend authoritatively calculates `overall_score` via [`calculate_overall_score()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/domain/candidates/scoring.py#L81).
3. Technical duration and container validity serve strictly as **boolean gates**; no synthetic point bonuses or continuous distance penalties are applied.
4. Downstream human review or future Stage 4 evaluation can perform post-expansion re-rating if empirical evidence later demands it.

---

## 6. Authoritative Validation Order & Refinement Lifecycle

### 6.1 Correct Lifecycle Order
To eliminate contradictions between duration validation and boundary refinement:

```
[ Step 1: LLM Anchor Extraction ]
  └── Model outputs semantic anchors with chunk-local segment IDs

[ Step 2: Anchor Validation ]
  ├── Check segment ID validity & contiguity
  └── Ground transcript_excerpt and evidence quotes

[ Step 3: Candidate-Window Construction ]
  └── Generates up to 3 candidate windows per anchor
  └── Invariant: Window MUST satisfy raw segment duration >= 10.0s here!

[ Step 4: Pre-Refinement Hard Validation ]
  ├── Validate: 10.0s <= (end_seconds - start_seconds) <= 60.0s
  └── Validate: 0.0 <= start_seconds < end_seconds <= source_duration_seconds
  └── Hard-reject any window < 10.0s (e.g. 9.5s raw interval is REJECTED here)

[ Step 5: Word-Timestamp Boundary Refinement ]
  ├── Runs ONLY on candidates that passed Step 4 (duration >= 10.0s)
  ├── Snaps start outwardly to word onset
  └── Snaps end outwardly into following silence cushion (up to 1.0s)

[ Step 6: Post-Refinement Revalidation ]
  ├── Confirm refined start >= 0.0 and refined end <= source_duration_seconds
  └── Confirm refined duration does not exceed max_duration_seconds (60.0s)
  └── If revalidation fails, revert safely to pre-refinement timestamps

[ Step 7: Deduplication & Final Ranking ]
  ├── Calculate overall_score via calculate_overall_score()
  ├── Apply greedy IoU Non-Maximum Suppression (iou_threshold = 0.50)
  └── Cap list at settings.display_limit (10)

[ Step 8: Persistence & Optional Rendering ]
  ├── Write short_candidates.json with all accepted and rejected records
  └── If render_clean_masters: render clean MP4s (0 accepted = clean exit 0)
```

### 6.2 The Sub-Minimum Invariant
**Boundary refinement must NEVER be used to inflate sub-minimum fragments into passing candidates.**
- A raw segment span measuring $<10.0\text{s}$ (e.g. 9.5s) is rejected in Step 4 as `DURATION_BELOW_MINIMUM`. It is **not** forwarded to `refine_candidate_boundaries()` in the hope that silence cushions will stretch it past 10.0s.
- Silence cushions exist solely to provide acoustic breath and prevent clipping words; they are not an algorithmic tool to bypass minimum duration requirements.

---

## 7. Edge Cases & Failure Handling

| Edge Case Scenario | Expected Pipeline Behavior |
|---|---|
| **Anchor at transcript start ($S_{\text{start}} = 0$)** | Backward search halts at 0. If anchor duration $< 10.0\text{s}$, forward search evaluates $S_{\text{end}} + 1$. If total duration remains $<10.0\text{s}$, window is rejected as `DURATION_BELOW_MINIMUM`. |
| **Anchor at transcript end ($S_{\text{end}} = N-1$)** | Forward search clamps at media duration. Boundary refinement cannot extend beyond container duration. |
| **Candidate Start Preceded by Long Monologue** | If 30 seconds of monologue precede the anchor with no terminal punctuation, fallback steps back segment-by-segment to the nearest boundary satisfying 10.0s. |
| **Malformed or Discontiguous Anchor IDs** | LLM outputs `[2, 5]`. Rejected immediately with typed reason code `DISCONTIGUOUS_ANCHOR`. |
| **Missing Word Timings** | If Faster-Whisper provides no word timestamps, `boundaries.py` clamps strictly to segment container bounds without crashing. |
| **Zero Viable Windows Generated** | If all windows exceed max duration or cross topic boundaries, candidate count is 0. Pipeline writes `short_candidates.json` with 0 accepted candidates and exits with code 0. |

---

## 8. Controlled Evaluation Plan

To avoid overfitting to specific clip counts or specific time windows, testing separates **Automated Correctness Invariants** from **Editorial Review Rubrics**:

### 8.1 Automated Invariant Suite (100% Pass Required)
1. **Duration Compliance**: Every accepted candidate satisfies $10.0\text{s} \le \text{duration} \le 60.0\text{s}$.
2. **Container Compliance**: Every accepted candidate satisfies $0.0 \le \text{start} < \text{end} \le \text{source\_duration}$.
3. **Word Integrity**: Zero words cut mid-syllable (verified via word start/end bounds).
4. **Evidence Grounding**: 100% of quotes in `transcript_excerpt` and `evidence` match transcript ground truth.
5. **Zero-Shorts Graceful Exit**: Long masters with no viable Shorts exit with status 0, zero media rendered, and valid candidate JSON persisted.

### 8.2 Six Controlled Evaluation Test Cases
- **Case 1: Multi-Segment Conversational Exchange**:
  - *Example*: Board-Game Master (`clip_01`, 49.19s).
  - *Automated Check*: Generates valid candidate $\ge 10.0\text{s}$ capturing the core narrative.
  - *Editorial Rubric*: Setup connects meaningfully to payoff.
- **Case 2: Punchline with Distant Setup**:
  - *Example*: Setup 40s prior to punchline.
  - *Automated Check*: Window duration does not exceed 60.0s.
  - *Editorial Rubric*: Clip remains intelligible without trailing rambles.
- **Case 3: Incomplete Trailing Thought**:
  - *Example*: Transcript ending with an uncompleted clause (*"and so then..."*).
  - *Automated Check*: Trailing uncompleted segment is excluded or window rejected.
  - *Editorial Rubric*: Clip lands on a natural conversational landing.
- **Case 4: Multiple Overlapping Anchors**:
  - *Example*: Two jokes within 6 seconds.
  - *Automated Check*: IoU NMS ($\text{IoU} \ge 0.50$) suppresses the lower-scoring window; exactly 1 candidate survives.
- **Case 5: Atomic Long Master (No Viable Short)**:
  - *Example*: Seamless 30s continuous thought where no sub-slice makes sense.
  - *Automated Check*: Exactly **0 accepted Shorts**; pipeline completes with exit code 0.
- **Case 6: Sub-Minimum Raw Segment (<10.0s)**:
  - *Example*: Exchange measuring 9.5s raw.
  - *Automated Check*: Correctly rejected as `DURATION_BELOW_MINIMUM` in Step 4; never forwarded to refinement.

---

## 9. Minimal Implementation Sequence & Test Checklist

### 9.1 File Modifications
1. **`backend/app/services/candidates/expansion.py` (NEW FILE)**:
   - `expand_anchors_to_candidates()`: Pure Python window construction, fallback, and validation.
2. **`backend/app/services/llm/prompts.py` (MODIFY)**:
   - Update short-clip prompt to request `LLMAnchorEvaluation` with chunk-local `[SEG_XX]` tags.
3. **`backend/app/api/v1/schemas/candidates.py` (MODIFY)**:
   - Add `LLMAnchorEvaluation` schema.
   - Add `UNKNOWN_SEGMENT_ID`, `DISCONTIGUOUS_ANCHOR`, and `EXCERPT_NOT_GROUNDED` to `ValidationReasonCode`.
4. **`backend/app/services/candidates/short_pipeline.py` (MODIFY)**:
   - Wire anchor expansion between raw LLM gathering and `deduplicate_and_rank_candidates()`.

### 9.2 Minimum Unit Test Checklist (`test_candidate_expansion.py`)
- [ ] `test_window_generation_expands_anchor_to_valid_duration()`
- [ ] `test_window_generation_caps_at_three_windows_per_anchor()`
- [ ] `test_window_generation_fallback_when_anchor_under_minimum_duration()`
- [ ] `test_window_generation_rejects_sub_minimum_window_before_refinement()`
- [ ] `test_window_generation_respects_max_duration_and_lookback_budget()`
- [ ] `test_anchor_validation_rejects_discontiguous_segment_ids()`
- [ ] `test_anchor_validation_rejects_ungrounded_transcript_excerpt()`
- [ ] `test_zero_shorts_when_all_windows_exceed_max_duration()`

---

## 10. Verification of Strict Read-Only Boundaries
- **Zero Application Code Modified**: No files in `backend/app/` or `backend/tests/` were edited.
- **Zero Invocations**: No LLMs, Ollama endpoints, ffmpeg rendering, or CLI commands were executed.
- **Artifacts Untouched**: All files under `input/`, `outputs/`, and `experimental_output/` remain completely unmodified.
- **Target Document**: Only [`docs/STAGE3_SHORT_DISCOVERY_IMPLEMENTATION_REFINEMENT.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_IMPLEMENTATION_REFINEMENT.md) was updated.
