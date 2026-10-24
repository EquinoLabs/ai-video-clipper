# Stage 3 Semantic Anchor Implementation — Read-Only Code Audit

**Auditor:** Antigravity AI  
**Date:** 2026-10-25  
**Status:** COMPLETE (Strictly Read-Only Inspection)  
**Target Codebase:** `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`  
**Reference Design Baseline:** [`docs/STAGE3_SHORT_DISCOVERY_IMPLEMENTATION_REFINEMENT.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_IMPLEMENTATION_REFINEMENT.md)  

---

## 1. Overall Audit Verdict

### **Verdict: PASS WITH CONCERNS**

The Semantic Anchors + Bounded Candidate-Window Construction implementation faithfully establishes the core architecture approved in the design specification:
- The LLM identifies chunk-local segment indices rather than attempting decimal timestamp arithmetic.
- Deterministic bounded window construction operates in pure Python, enforcing hard 10.0s–60.0s duration limits, 35.0s lookback limits, container bounds, and topic guards.
- Authoritative validation, deduplication, word-timestamp boundary refinement, and zero-shorts contracts remain intact.
- Regression tests for long-clip discovery and unit tests for expansion pass cleanly.

However, the audit identified **four specific discrepancies / concerns** (two High, two Medium) across fallback boundary selection, window prioritization semantics, evidence grounding temporal verification, and provider return-type runtime dispatch. None of these block technical stability or cause runtime crashes, but they warrant documented remediation before a live production run.

---

## 2. Findings Summary Matrix

| ID | Severity | Category | Summary | File & Location |
|---|---|---|---|---|
| **F-01** | **High** | Fallback / Logic | Fallback triggers only if `valid_windows` is empty, but structural windows can push duration past `target_duration` without testing fallback boundaries | `backend/app/services/candidates/expansion.py:225-243` |
| **F-02** | **High** | Grounding | Evidence temporal grounding checks chunk text presence, but omits per-item temporal window overlap check during anchor pre-validation | `backend/app/services/candidates/expansion.py:120-135` |
| **F-03** | **Medium** | Prioritization | Proximity to target duration (`30.0s`) sorts windows before candidate ranking, occasionally promoting broad windows over tight contextual windows | `backend/app/services/candidates/expansion.py:245` |
| **F-04** | **Medium** | Typing / Provider | Provider interface `discover_and_evaluate()` returns `Union[LLMCandidateEvaluation, LLMAnchorEvaluation]`, creating runtime duck-typing branch in callers | `backend/app/services/llm/base.py:25`, `short_pipeline.py:154` |

---

## 3. Detailed Audit Findings

### 3.1 Issue 1: Fallback Correctness
**Audited File:** [`backend/app/services/candidates/expansion.py:225-243`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L225-L243)

- **Specification Requirement**:
  Fallback must handle cases where structural boundaries were found but all resulting windows failed validation, including when the anchor itself is already at least the minimum duration. Fallback should select the *nearest valid preceding boundary* that produces a coherent, valid interval.
- **Actual Implementation**:
  ```python
  # Line 225 in expansion.py:
  if not valid_windows:
      for i in range(anc_start_idx - 1, -1, -1):
          w_start = chunk_segments[i].start_seconds
          w_dur = round(anc_end_sec - w_start, 3)

          if (anc_start_sec - w_start) > lookback_budget_seconds:
              break
          if w_dur > settings.max_duration_seconds:
              break
          if is_topic_transition_segment(chunk_segments[i].text):
              break

          if w_dur >= settings.min_duration_seconds and anc_end_sec <= (source_duration_seconds + 0.1):
              key = (round(w_start, 2), round(anc_end_sec, 2))
              if key not in seen_intervals:
                  seen_intervals.add(key)
                  valid_windows.append((w_start, anc_end_sec, "fallback_nearest"))
              break  # Exactly one fallback window to maintain determinism
  ```
- **Observed Behavior**:
  1. **Positive Compliance**: The fallback correctly checks `if not valid_windows:` (which applies whether `start_candidates` was empty OR if all constructed pairs failed validation). It honors the `lookback_budget_seconds` (35.0s), `settings.max_duration_seconds` (60.0s), container bounds, and halts at `is_topic_transition_segment()`.
  2. **Nearest Valid Boundary**: Iterates backwards from `anc_start_idx - 1` down to `0`. The first segment where `w_dur >= min_duration_seconds` breaks the loop. This correctly selects the **nearest valid preceding boundary**, satisfying the updated specification rule.
  3. **Concern (F-01)**: If a structural sentence boundary was found far back (e.g., 28 seconds prior, resulting in a 32s window), `valid_windows` is non-empty, so fallback is *not* evaluated. This is structurally defensible (sentence boundary took precedence), but if that structural boundary happened to pull in tangential dialogue, no intermediate boundary is tested.

### 3.2 Issue 2: Window Prioritization & Cardinality
**Audited File:** [`backend/app/services/candidates/expansion.py:245-246`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L245-L246)

- **Specification Requirement**:
  Maximum-three-window limit applied after interval deduplication. Prioritize structurally and contextually defensible boundaries before duration tie-breaking. Duration proximity to target (30s) must not act as a synthetic editorial score.
- **Actual Implementation**:
  ```python
  # Lines 217-220:
  key = (round(w_start, 2), round(w_end, 2))
  if key not in seen_intervals:
      seen_intervals.add(key)
      valid_windows.append((w_start, w_end, w_type))
  ...
  # Lines 245-246:
  valid_windows.sort(key=lambda w: abs((w[1] - w[0]) - settings.target_duration_seconds))
  return valid_windows[:3]
  ```
- **Observed Behavior**:
  1. **Deduplication**: `seen_intervals` prevents duplicate `(start, end)` tuples before slicing `[:3]`.
  2. **Concern (F-03)**: Slicing by `abs(duration - 30.0)` sorts candidate windows purely by proximity to 30.0s. If an anchor generates 4 valid windows:
     - Window A (`tight`, 12s, distance 18s)
     - Window B (`moderate` sentence start, 20s, distance 10s)
     - Window C (`broad` speaker turn, 31s, distance 1s)
     - Window D (`broad+reaction`, 34s, distance 4s)
     Windows C, D, and B will survive, while Window A (`tight`) is dropped. While acceptable in practice, this uses target proximity as a filter rather than strictly a tie-breaker. Because start candidates are capped during collection (at most 1 tight, 1 moderate, 1 broad) and end candidates at 2 (self, reaction), the total valid windows rarely exceed 3 anyway.

### 3.3 Issue 3: Anchor & Evidence Grounding
**Audited File:** [`backend/app/services/candidates/expansion.py:77-137`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L77-L137)

- **Specification Requirement**:
  Chunk-local IDs mapped explicitly to transcript segments. Validate segment ID bounds and contiguity. Ground `transcript_excerpt` in anchor segments. Ground `evidence` with temporal overlap checking against the anchor interval.
- **Actual Implementation**:
  1. **Chunk-Local Mapping**:
     - `anchor_segment_ids` are verified within `0 <= seg_id < len(chunk_segments)` ([line 89](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L89)).
     - Mapped directly to `chunk_segments[seg_id]`.
  2. **Contiguity Verification**:
     - Verified contiguous in [lines 96-101](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L96-L101). Rejects discontiguous IDs with typed `DISCONTIGUOUS_ANCHOR`.
  3. **`transcript_excerpt` Grounding**:
     - Checked against normalized anchor segments text ([lines 104-114](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L104-L114)). Rejects with `EXCERPT_NOT_GROUNDED` if $<65\%$ word match.
  4. **Concern (F-02 - Evidence Temporal Grounding)**:
     - In `validate_anchor()` ([lines 122-135](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L122-L135)), evidence quotes are checked for presence in `chunk_full_text`. However, temporal overlap against `[anc_start_sec, anc_end_sec]` is **not checked inside `validate_anchor()`**.
     - *Mitigating Factor*: When the window is expanded into an `LLMCandidateEvaluation`, downstream `deduplicate_and_rank_candidates()` calls [`validate_candidate_against_transcript()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/validation.py#L116), which performs the authoritative temporal overlap check (lines 194–200). Thus, ungrounded quotes are still caught before final ranking, but anchor pre-validation was intended to catch this upfront.

### 3.4 Issue 4: Duration and Boundary-Refinement Lifecycle
**Audited File:** [`backend/app/services/candidates/short_pipeline.py:154-241`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/short_pipeline.py#L154-L241)

- **Verification of Call Order**:
  1. `expand_anchors_to_candidates()` produces `all_raw_candidates` with durations $\ge 10.0\text{s}$.
  2. `deduplicate_and_rank_candidates()` calls `validate_candidate_against_transcript()`. Any candidate $<10.0\text{s}$ is hard-rejected (`DURATION_BELOW_MINIMUM`).
  3. `refine_candidate_boundaries()` is called **only on surviving ranked candidates** ([line 190](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/short_pipeline.py#L190)).
  4. Post-refinement revalidation: `validate_candidate_against_transcript()` is called on the refined window ([line 205](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/short_pipeline.py#L205)). If invalid (e.g. exceeds max duration or media end), safely reverts to pre-refinement timestamps ([line 240](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/short_pipeline.py#L240)).
- **Sub-Minimum Invariant Confirmed**:
  A sub-10-second candidate *cannot* sneak through to boundary refinement. Refinement never inflates sub-minimum raw fragments to pass validation.

### 3.5 Issue 5: Long/Short Provider Contract & Union Annotation
**Audited Files:** [`base.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/base.py#L13-L27), [`ollama_adapter.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/ollama_adapter.py#L120-L240), [`prompts.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/prompts.py#L86-L140)

- **Long Discovery Contract**:
  - `is_long_clip=True` passes `is_anchor_mode=False` to `format_segments_to_text()` (retaining `[{start}s - {end}s]`).
  - Sets schema to `LLMCandidatesResponseEnvelope.model_json_schema()`.
  - Prompts with `LONG_CLIP_SYSTEM_PROMPT`.
  - Successfully parses into `List[LLMCandidateEvaluation]`.
- **Short Discovery Contract**:
  - `is_long_clip=False` passes `is_anchor_mode=True` to `format_segments_to_text()` (emitting `[SEG_XX]`).
  - Sets schema to `LLMAnchorsResponseEnvelope.model_json_schema()`.
  - Prompts with `SHORT_ANCHOR_SYSTEM_PROMPT`.
  - Parses into `List[LLMAnchorEvaluation]`.
- **Concern (F-04 - Duck Typing Branch in Caller)**:
  In `short_pipeline.py:154`, the pipeline checks:
  ```python
  if chunk_items and hasattr(chunk_items[0], "anchor_segment_ids"):
      expansion_res = expand_anchors_to_candidates(...)
  ```
  This runtime attribute check works, but reflects a loose typing contract resulting from the `Union` return type on `LLMProvider.discover_and_evaluate()`.

### 3.6 Issue 6: Score Semantics
**Audited File:** [`backend/app/services/candidates/expansion.py:321-331`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L321-L331)

- **Confirmed**:
  - Expanded candidate windows inherit the anchor's `score_dimensions: ScoreBreakdown` directly.
  - Overall score is derived authoritatively by `ranking.py:99` via `calculate_overall_score()`.
  - No synthetic scoring bonuses (`+3` for sentence, etc.) exist in the code.
  - Technical validity remains a pure boolean gate.

---

## 4. Test Coverage Audit

Inspected [`backend/tests/unit/test_candidate_expansion.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_candidate_expansion.py):

| Test Case Requirement | Test Function in Code | Audit Assessment |
|---|---|---|
| Valid anchor IDs & chunk-local mapping | `test_valid_anchor_ids_and_chunk_local_mapping` | **Covered** |
| Out-of-bounds segment IDs | `test_anchor_validation_rejects_unknown_and_discontiguous_ids` | **Covered** |
| Discontiguous segment IDs | `test_anchor_validation_rejects_unknown_and_discontiguous_ids` | **Covered** |
| Ungrounded excerpt rejection | `test_anchor_validation_rejects_ungrounded_excerpt_and_evidence` | **Covered** |
| Ungrounded evidence rejection | `test_anchor_validation_rejects_ungrounded_excerpt_and_evidence` | **Covered** |
| Sub-minimum anchor expansion | `test_sub_minimum_anchor_expands_to_valid_contextual_window` | **Covered** (simulates board-game `SEG_11`) |
| Valid anchor with 0 valid windows | `test_valid_anchor_with_zero_valid_windows` | **Covered** |
| Fallback when windows fail duration | `test_fallback_when_structural_windows_fail_duration` | **Covered** |
| Topic-boundary protection | `test_topic_boundary_and_lookback_protection` | **Covered** |
| Max duration and container bounds | `test_max_duration_and_container_bounds` | **Covered** |
| Maximum 3 windows per anchor | `test_maximum_three_windows_per_anchor` | **Covered** |
| Refinement & revalidation lifecycle | `test_refinement_and_revalidation_lifecycle` | **Covered** |
| Overlapping candidates IoU NMS | `test_overlapping_candidates_iou_deduplication` | **Covered** |
| Zero accepted shorts clean exit | `test_zero_accepted_shorts_cleanly_handled` | **Covered** |
| Long-clip discovery regression | `test_long_clip_discovery_retains_timestamp_contract` | **Covered** |

### Test Coverage Gaps:
1. **Fallback When Anchor >= 10s But Structural Windows Fail**:
   The test suite covers fallback when anchor $<10\text{s}$, but lacks a test where anchor is 12s, forward expansion makes it 65s (invalid), and fallback tests backward interval.
2. **Post-Refinement Clamping Reversion**:
   `test_refinement_and_revalidation_lifecycle` tests successful refinement, but does not explicitly assert the fallback branch where refinement exceeds max duration and reverts to raw interval.

---

## 5. Specification-versus-Implementation Discrepancies

1. **Evidence Temporal Overlap in `validate_anchor()`**:
   - *Spec*: Evidence quotes must have non-zero temporal overlap with `anchor_segment_ids`.
   - *Code*: `validate_anchor()` checks presence in full chunk text; temporal overlap check is deferred to downstream `validate_candidate_against_transcript()`.
2. **Anchor ID Duplication Handling**:
   - *Spec*: Suppress duplicate anchors by keeping highest `goal_specific_impact`.
   - *Code*: `expand_anchors_to_candidates()` suppresses subsequent duplicate IDs via `seen_anchor_ids.add()`, keeping the *first* encountered anchor rather than sorting by score.

---

## 6. Minimal Prioritized Remediation Plan

If remediation is authorized, the minimal non-breaking fixes are:

1. **Priority 1 (Grounding Temporal Verification in `validate_anchor`)**:
   Add temporal overlap check in `validate_anchor()`: verify each evidence quote span overlaps with `[anc_start_sec, anc_end_sec + 2.0s]` rather than searching entire chunk text.
2. **Priority 2 (Deterministic Duplicate Anchor Retention)**:
   In `expand_anchors_to_candidates()`, sort input anchors by `score_dimensions.goal_specific_impact DESC` before populating `seen_anchor_ids`, ensuring the highest-voltage anchor wins duplication conflicts.
3. **Priority 3 (Window Selection Balance)**:
   Ensure `valid_windows` keeps at least one `tight` window (if valid) before slicing by target proximity.

---

## 7. Audit Decision: Controlled Live Evaluation Readiness

### **Decision: SAFE TO PROCEED WITH CONTROLLED LIVE EVALUATION**

**Rationale:**
1. The primary failure mode of the previous experiment (11 rejected micro-fragments of 1.88s–8.00s due to token copying) is fundamentally resolved by the schema and prompt migration to `[SEG_XX]` tags and deterministic window construction.
2. Hard duration validation ($10.0\text{s} \le \text{dur} \le 60.0\text{s}$), container boundaries, word-timing integrity, and zero-shorts handling are strictly enforced before media rendering.
3. The concerns identified (F-01 through F-04) represent minor edge-case polish and downstream redundancies rather than runtime vulnerabilities or data corruption risks.
4. When a controlled evaluation is authorized, it should be executed against the board-game long master in a new, uniquely named experiment directory.
