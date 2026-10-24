# Stage 3 — Short Discovery Strategy Design Proposal (Revised Implementation Plan)

**Author:** Antigravity AI  
**Date:** 2026-10-24  
**Status:** IMPLEMENTATION-READY SPECIFICATION (Read-Only Design Revision)  
**Target:** AI Video Clipper — Stage 3 Short-Clip Discovery Pipeline  

---

## 1. Executive Summary & Approved Decisions

Following the controlled evaluation of Stage 2 (long-master extraction) and Stage 3 (short-clip discovery) on the 49.19-second board-game conversation from *The Tonight Show Starring Jimmy Fallon* (guest Anne Hathaway), all 11 candidate proposals emitted by Ollama `qwen2.5:7b` were rejected due to durations between 1.80s and 8.00s, violating the 10.0-second minimum duration threshold (`clip_min_seconds: 10.0`).

The prior diagnosis established that the LLM copied segment boundary timestamps of isolated quotes (e.g. *"I play for money to"*) without the setup necessary for standalone coherence.

### Approved Decisions
1. **Approach A Selected**: The LLM extracts semantic anchors and identifies stable segment IDs; Python deterministically constructs, validates, and refines candidate windows.
2. **Authoritative Timestamp Ownership**: The LLM does not output final start/end seconds or backend overall scores. Python resolves segment IDs to Whisper word timings and enforces all mathematical constraints.
3. **No Unneeded LLM Calls**: Approach B (two-pass LLM discovery) is rejected as redundant and latent. A single LLM call is used.
4. **Preserved Invariants**: Configured 10.0s–60.0s limits remain unchanged. Zero accepted Shorts remains a valid, cleanly supported outcome. Stage 2 and existing short rendering interfaces remain untouched.
5. **Replacement of Greedy Expansion**: Bounded candidate-window construction replaces greedy outward expansion with a discrete, ranked set of bounded windows per anchor.

---

## 2. Anchor Schema and Grounding Rules

### 2.1 LLM Output Schema: `LLMAnchorEvaluation`
The LLM prompt is updated to request semantic anchors rather than final video clip intervals. The LLM must output structured JSON conforming to the following Pydantic schema:

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
    anchor_id: str = Field(
        ..., description="Unique anchor identifier, e.g. 'anc_001'"
    )
    anchor_segment_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="Contiguous list of 1 to 4 transcript segment IDs containing the anchor",
    )
    anchor_type: AnchorType = Field(
        ..., description="Categorical classification of the semantic anchor"
    )
    hook: str = Field(
        ..., min_length=5, max_length=150, description="Brief explanation of the hook or punchline"
    )
    transcript_excerpt: str = Field(
        ..., min_length=5, description="Verbatim quote or core line of the anchor"
    )
    score_dimensions: ScoreBreakdown = Field(
        ..., description="Standard 8-dimension ratings (0.0 to 5.0) evaluating anchor quality"
    )
    rationale: str = Field(
        ..., min_length=10, description="Editorial rationale explaining why this moment is compelling"
    )
    evidence: List[EvidenceItem] = Field(
        ..., min_length=1, description="Verbatim quote items copied from the transcript"
    )
    confidence_label: ConfidenceLabel = Field(
        default=ConfidenceLabel.HIGH, description="Model self-reported confidence"
    )
```

### 2.2 Segment Presentation in the User Prompt
To prevent token-copying of timestamps while preserving temporal order and readability, `format_segments_to_text()` is adapted for short-mode prompting to expose explicit segment tags:

```text
[SEG_00] Jimmy: Thank you for playing reverse charades with me. You're a great partner...
[SEG_01] Jimmy: I mean, are you are you competitive when you play games? Do you play games at home...
...
[SEG_10] Anne: Because it's fun. It's all good, but the other one really wants to win and I don't throw the games.
[SEG_11] Anne: You know, I go I really and I play for I play for money to.
```

### 2.3 Backend Validation and Grounding Rules
Before any window construction occurs, raw anchors pass through authoritative backend validation:
1. **Segment ID Validity**: Every ID in `anchor_segment_ids` must exist in `[0, len(segments) - 1]`. Any unknown ID results in immediate rejection (`UNKNOWN_SEGMENT_ID`).
2. **Contiguity Invariant**: `anchor_segment_ids` must be strictly contiguous (e.g., `[10, 11]` is valid; `[8, 11]` is rejected as `DISCONTIGUOUS_ANCHOR_SEGMENTS`).
3. **Evidence Grounding**: The existing [`_find_quote_spans_in_segments()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/validation.py#L43) validates that every quote in `evidence` exists verbatim in the transcript. Furthermore, the quote must temporally overlap with the anchor segments. If ungrounded, the anchor is rejected (`EVIDENCE_NOT_GROUNDED`).
4. **Anchor Deduplication**: If multiple anchors reference identical or subset segment ranges with identical anchor types, only the highest-scoring anchor is retained for window construction.

---

## 3. Bounded Candidate-Window Construction Algorithm

Instead of a greedy while-loop that expands outward until a threshold is hit, the backend applies a **bounded combinatorial window generator**. This guarantees that:
- Combinatorial explosion is impossible (maximum of 3 to 5 candidate windows generated per anchor).
- Candidates are anchored to structural transcript units (speaker turns and sentence boundaries), not arbitrary frame steps.
- Durations are strictly bounded between `min_duration_seconds` (10.0s) and `max_duration_seconds` (60.0s) before expensive refinement.

### 3.1 Structural Anchor Points
Let the validated anchor occupy segments $[S_{\text{anc\_start}}, S_{\text{anc\_end}}]$.
1. **Backward Boundary Candidates ($B_{\text{start}}$)**:
   Search backward from $S_{\text{anc\_start}}$ for candidate starting segments:
   - $B_0$: $S_{\text{anc\_start}}$ (the anchor itself, if already $\ge 10.0\text{s}$).
   - $B_1$ (Immediate Preceding Sentence / Turn): The most recent segment boundary prior to the anchor that begins with a capitalized sentence after terminal punctuation (`.`, `!`, `?`) or a speaker turn transition.
   - $B_2$ (Topic Initiation / Premise Setup): The earliest segment within a 45-second lookback that initiates the conversational premise (e.g. host question, topic pivot, or first-person narrative intro).
   - *Filter*: Any $B_i$ that would cause $(S_{\text{anc\_end}}.\text{end} - B_i.\text{start}) > \text{max\_duration}$ is discarded.
2. **Forward Boundary Candidates ($F_{\text{end}}$)**:
   Search forward from $S_{\text{anc\_end}}$ for candidate ending segments:
   - $F_0$: $S_{\text{anc\_end}}$ (the anchor payoff itself).
   - $F_1$ (Conversational Resolution / Reaction): The segment following the anchor that contains terminal punctuation, speaker acknowledgment, or concluding remark.
   - *Filter*: Any $F_j$ that exceeds `source_duration_seconds` or causes total duration $> \text{max\_duration}$ is discarded.

### 3.2 Bounded Window Set Generation
Form candidate pairs $(B_i, F_j)$ and filter strictly:
$$\text{RawWindows} = \{ [B_i, F_j] \mid B_i \le S_{\text{anc\_start}} \le S_{\text{anc\_end}} \le F_j \}$$
1. **Hard Duration Filter**:
   $$\text{duration} = \text{segments}[F_j].\text{end\_seconds} - \text{segments}[B_i].\text{start\_seconds}$$
   Discard if $\text{duration} < 10.0\text{s}$ or $\text{duration} > 60.0\text{s}$.
2. **Cap Window Cardinality**:
   Order valid windows by proximity to `target_duration_seconds` (default: 30.0s). Retain at most **3 candidate windows per anchor** (typically: Tight, Target, and Wide).

```
   Transcript:  [--B2: Setup--] ... [--B1: Context--] ... [===ANCHOR===] ... [--F1: Reaction--]
                                                          └──────┬──────┘
   Window 1 (Tight, if >=10s):                           [==============F1]
   Window 2 (Target Context):               [───────────────────────────F1]
   Window 3 (Complete Narrative Arc): [─────────────────────────────────F1]
```

---

## 4. Candidate-Window Scoring, Selection & Heuristics

To evaluate generated windows objectively without conflating LLM perception with algorithmic construction, the scoring pipeline cleanly separates four layers:

### 4.1 Layer 1: Semantic Anchor Quality (LLM-Derived)
The anchor inherits the LLM's 8-dimension ratings:
- `hook_strength`, `goal_relevance`, `goal_specific_impact`, `specificity_insight`.
These define the core editorial value of the underlying moment.

### 4.2 Layer 2: Technical Validity (Authoritative Boolean Checks)
A window must pass 100% of these checks or it is rejected:
- $\text{start\_seconds} \ge 0.0$.
- $\text{end\_seconds} \le \text{source\_duration\_seconds} + 0.1\text{s}$.
- $10.0\text{s} \le (\text{end\_seconds} - \text{start\_seconds}) \le 60.0\text{s}$.
- Quotes in `evidence` are verbatim substrings of transcript segments within the window.

### 4.3 Layer 3: Context & Completeness Indicators (Explicit Heuristics)
Because automated heuristics cannot mathematically "prove" narrative completeness, we treat completeness indicators strictly as **transparent ranking adjustments**, not absolute gates:
- **Sentence Start Bonus (+3 points)**: Window starts on a word following terminal punctuation rather than mid-clause conjunctions (`"and"`, `"because"`, `"but"`).
- **Speaker Continuity Bonus (+3 points)**: Window contains at least two distinct speaker turns if conversational, or starts at the beginning of a monologue turn.
- **Payoff Landing Bonus (+4 points)**: Window ends on terminal punctuation followed by acoustic silence ($\ge 0.35\text{s}$) before any subsequent speech.
- **Target Duration Proximity (-0.5 points per second)**: Linear penalty for distance from `target_duration_seconds` (30.0s).

### 4.4 Layer 4: Final Editorial Ranking & Deduplication
1. **Composite Score**: Derived from `calculate_overall_score(dimensions)` combined with Layer 3 heuristics (scaled 0–100).
2. **IoU Non-Maximum Suppression (NMS)**:
   - When candidate windows from the same or different anchors overlap with $\text{IoU} \ge 0.50$, the window with the higher composite score is selected.
   - **Tie-Breaker**: Closer to `target_duration_seconds` (30.0s); earlier in media.
   - This explicitly allows a tightly cut 28s window to defeat an overly broad 55s window if the 28s window delivers the payoff with higher pacing and conciseness.

---

## 5. Artifact Verification: Board-Game Long Master (`clip_01`)

To ground this specification in physical evidence, we directly inspected the evaluation transcript artifact at [`experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/transcript.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/transcript.json) and metadata at [`metadata.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/metadata.json).

### 5.1 Verified Artifact Facts
1. **Source & Container Duration**:
   - `metadata.json` confirms: `source_start_seconds: 11.73`, `source_end_seconds: 60.92`.
   - Local container duration: `49.19` seconds (`local_start: 0.0`, `local_end: 49.19`).
2. **Segment Boundaries & Word Timings**:
   - `SEG_06`: `19.72s - 27.72s` (duration: 8.00s). First word `"Why"` at 19.72s; last word `"too"` ends at 27.72s.
   - `SEG_07`: `27.72s - 31.44s` (duration: 3.72s). Text: *"And it turns out motherhood is often me, and I like to watch them when yeah"*.
   - `SEG_08`: `31.44s - 35.96s` (duration: 4.52s). Text: *"My kids are very competitive. Well, my one daughter is yeah"*.
   - `SEG_09`: `35.96s - 37.84s` (duration: 1.88s). Text: *"Yeah, the other one doesn't really care"*.
   - `SEG_10`: `38.39s - 43.83s` (duration: 5.44s). Text: *"Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games"*.
   - `SEG_11`: `43.83s - 47.69s` (duration: 3.86s). Text: *"You know, I go I go I go I really and I play for I play for money to"*.
3. **Location of Final Words**:
   - In `SEG_11`, word-by-word inspection confirms:
     - Word `"money"`: `47.13s - 47.37s`.
     - Final word `"to"`: `47.37s - 47.69s`.
4. **Speaker Diarization & Audio Event Limitations**:
   - In `transcript.json`, every segment has `speaker_label: null`. Faster-Whisper tiny did **not** perform diarization.
   - Faster-Whisper does **not** transcribe non-speech acoustic events. There are no tokens for `[laughter]`, `[applause]`, or laughter audio in the transcript.
   - Segment 11 ends at `47.69s`, while the media file extends to `49.19s` (a 1.50s trailing audio tail). In the actual video, this tail contains Jimmy's laughter and room applause. However, **this is an acoustic observation from the video, not an explicit data field in `transcript.json`**.
   - Therefore, algorithms must rely on word-timing silence gaps and container limits, not non-existent laughter tokens.

### 5.2 Window Evaluation for the Board-Game Case
- **Window A: `19.72s - 47.69s` (Duration: 27.97s)**:
  - Supported directly by `transcript.json` segment bounds (`SEG_06` to `SEG_11`).
  - Begins with Jimmy introducing the kids topic (`19.72s`); ends with Anne saying *"to"* (`47.69s`).
- **Window B: `19.72s - 48.69s` (Refined Window, Duration: 28.97s)**:
  - When [`refine_candidate_boundaries()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/boundaries.py#L50) runs on Window A with `outward_cushion_seconds: 1.0`, it seeks into the silence gap following `47.69s`. Since no words follow before media end (`49.19s`), it adds the 1.0s cushion cleanly, ending at `48.69s`.
  - This preserves the punchline decay and room laughter acoustically without violating media bounds.

---

## 6. Authoritative Processing Order

The pipeline executes in 8 discrete, linear steps:

```
Step 1: Anchor Extraction (LLM)
        └── Output: List[LLMAnchorEvaluation] with anchor_segment_ids

Step 2: Anchor ID & Evidence Validation (Python)
        ├── Check IDs exist in transcript [0, N-1]
        ├── Check contiguity of anchor segments
        ├── Check evidence quotes grounded in transcript
        └── Rejection code if invalid: UNKNOWN_SEGMENT_ID, DISCONTIGUOUS_ANCHOR, EVIDENCE_NOT_GROUNDED

Step 3: Bounded Candidate-Window Construction (Python)
        ├── Backward expansion to candidate sentence/turn starts (B_0, B_1, B_2)
        ├── Forward expansion to candidate resolution ends (F_0, F_1)
        └── Generate <= 3 candidate windows per anchor

Step 4: Window Duration & Media Bound Validation (Python)
        ├── Enforce: 10.0s <= (end - start) <= 60.0s
        ├── Enforce: 0.0 <= start < end <= source_duration
        └── Reject invalid windows: DURATION_BELOW_MINIMUM, DURATION_EXCEEDS_MAXIMUM

Step 5: Word-Timestamp Boundary Refinement (Python)
        ├── Snap start outwardly to first spoken word onset
        ├── Snap end outwardly into following silence cushion (up to 1.0s)
        └── Enforce word integrity (boundaries.py)

Step 6: Post-Refinement Revalidation (Python)
        └── Confirm refined window still satisfies bounds and duration limits

Step 7: Deduplication & Final Global Ranking (Python)
        ├── Calculate overall_score + completeness heuristics
        ├── Apply IoU Non-Maximum Suppression (iou_threshold = 0.50)
        └── Cap at display_limit (default: 10)

Step 8: Persistence & Optional Rendering (Python)
        ├── Save short_candidates.json (auditing all accepted and rejected records)
        └── If render_clean_masters: render accepted clips (0 clips = clean no-op)
```

---

## 7. Controlled Quality Evaluation Plan

To systematically verify the new discovery pipeline without overfitting to a single interview clip, we define an evaluation suite across 6 test profiles:

### 7.1 Evaluation Test Profiles
1. **Coherent Multi-Segment Comedic Exchange**:
   - *Input*: Board-game long master (`clip_01`, 49.19s).
   - *Expected Behavior*: Anchor at `SEG_11` expands backward across `SEG_06–10`, generating an accepted ~28–29s candidate.
2. **Short Punchline with Distant Setup**:
   - *Input*: Long master where setup is 45s earlier than the punchline.
   - *Expected Behavior*: Window builder produces a valid 30–50s candidate; does not truncate to just the punchline.
3. **Incomplete Thought at End of Transcript**:
   - *Input*: Segment ending with an trailing conjunction (`"and so then I..."`) without resolution.
   - *Expected Behavior*: Window builder rejects forward expansion or drops anchor due to lack of payoff.
4. **Multiple Overlapping Anchors**:
   - *Input*: Conversation with two comedic beats within 10 seconds of each other.
   - *Expected Behavior*: IoU deduplication suppresses the lower-scoring window; exactly one clean clip survives.
5. **Atomic Long Master (No Viable Short)**:
   - *Input*: A tightly wound 32-second continuous explanation where any sub-slice $<30\text{s}$ destroys meaning.
   - *Expected Behavior*: 0 Shorts accepted; pipeline cleanly exits with code 0 and logs zero-shorts artifact.
6. **Near-Boundary Candidate**:
   - *Input*: An exchange measuring exactly 9.8s raw.
   - *Expected Behavior*: Refinement cushion or backward sentence expansion extends it past 10.0s, or it is safely rejected without crash.

### 7.2 Acceptance Criteria

| Category | Metric | Acceptance Standard |
|---|---|---|
| **Technical** | Hard Duration Compliance | **100%** of accepted candidates satisfy $10.0\text{s} \le \text{duration} \le 60.0\text{s}$. |
| **Technical** | Media Bound Compliance | **100%** of candidate intervals satisfy $0.0 \le \text{start} < \text{end} \le \text{source\_duration}$. |
| **Technical** | Word Integrity | **0** words cut mid-syllable (verified via Whisper word boundary checks). |
| **Technical** | Evidence Grounding | **100%** of evidence quotes match verbatim in transcript. |
| **Editorial** | Standalone Intelligibility | Blind review: clip makes sense without viewing preceding video context. |
| **Editorial** | Narrative Payoff | Clip does not end mid-sentence or right before a punchline. |
| **Pipeline** | Zero-Short Handling | Pipeline completes with exit code 0 when 0 candidates qualify. |

---

## 8. Minimal Implementation Plan

### 8.1 Affected Files
The proposed change touches only 4 files in `backend/app/`:

1. **`backend/app/services/candidates/expansion.py` (NEW FILE)**:
   - Implements `expand_anchor_to_candidate_windows()`.
   - Pure, deterministic Python logic. Zero external dependencies beyond standard library and pydantic.
2. **`backend/app/services/llm/prompts.py` (MODIFY)**:
   - Update `build_user_prompt(is_long_clip=False)` to render `[SEG_XX]` tags.
   - Update `SYSTEM_PROMPT` to describe anchor extraction instead of interval guessing.
3. **`backend/app/api/v1/schemas/candidates.py` (MODIFY)**:
   - Add `LLMAnchorEvaluation` schema.
   - Add `UNKNOWN_SEGMENT_ID` and `DISCONTIGUOUS_ANCHOR` to `ValidationReasonCode`.
4. **`backend/app/services/candidates/short_pipeline.py` (MODIFY)**:
   - In Step 5/6, pass raw LLM anchors through `expansion.py` before duration validation and ranking.

### 8.2 Proposed Unit Tests (`backend/tests/unit/test_candidate_expansion.py`)
1. `test_expand_anchor_expands_sub_ten_second_quote_to_valid_window()`
2. `test_expand_anchor_respects_sentence_boundaries()`
3. `test_expand_anchor_rejects_unknown_segment_ids()`
4. `test_expand_anchor_caps_windows_at_max_duration()`
5. `test_expand_anchor_handles_empty_transcript_cleanly()`
6. `test_expand_anchor_deduplicates_overlapping_windows()`

### 8.3 Implementation Sequence
1. **Phase 1**: Write unit tests in `test_candidate_expansion.py` with mock segment fixtures.
2. **Phase 2**: Implement `expansion.py` to satisfy unit tests.
3. **Phase 3**: Add `LLMAnchorEvaluation` to schemas and update prompt formatting in `prompts.py`.
4. **Phase 4**: Wire `expansion.py` into `short_pipeline.py` and run test suite.
5. **Phase 5**: Execute controlled Stage 3 test run on `clip_01`.

---

## 9. Verification of Read-Only Status

- **Zero Code Changes**: No Python source files, prompts, schemas, tests, or configuration settings were modified.
- **Zero Invocations**: No Ollama models, external LLM endpoints, ffmpeg rendering, or CLI processes were run.
- **Zero Artifact Modifications**: All files in `outputs/`, `input/`, and `experimental_output/` remain strictly unmodified.
- **Artifact Written**: The complete revised specification has been recorded in [`docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md).
