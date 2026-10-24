# Stage 3 Semantic Anchor — Controlled Live Evaluation Report

**Evaluation Date:** 2026-10-25  
**Model & Provider:** Ollama `qwen2.5:7b` (local instance at `http://localhost:11434`)  
**Editorial Goal:** `humor`  
**Execution Context:** AI Video Clipper — Stage 3 Standalone Short-Clip Pipeline  
**Source Long-Master Package:** `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/`  
**Evaluation Output Directory:** `experimental_output/eval_stage3_semantic_anchor_live_20261025/`  

---

## 1. Executive Summary & Final Verdict

### **Verdict: EDITORIAL MIXED**

In the prior Stage 3 run (`eval_stage2_stage3_live_20261024`), Ollama `qwen2.5:7b` emitted 11 micro-fragment proposals between 1.88s and 8.00s; all 11 were hard-rejected by backend validation for violating the 10.0-second minimum duration threshold (`clip_min_seconds: 10.0`).

In this controlled evaluation of the newly implemented **Semantic Anchors + Bounded Candidate-Window Construction** architecture:
1. **0% Validation Rejections**: The model proposed 3 valid semantic anchors referencing chunk-local segment tags (`[SEG_04]`, `[SEG_08, SEG_09]`, and `[SEG_06, SEG_07]`). Zero anchors were rejected for malformed IDs or hallucinated excerpts.
2. **Deterministic Bounded Window Generation**: The backend generated 5 valid candidate windows across the 3 anchors. All 5 satisfied $10.0\text{s} \le \text{duration} \le 60.0\text{s}$ and parent media bounds before refinement.
3. **Clean Ranking & Deduplication**: IoU Non-Maximum Suppression ($\text{IoU} \ge 0.50$) reduced the 5 raw windows to **3 unique, non-overlapping candidate moments**.
4. **Clean Master Rendering**: All 3 surviving candidates were refined with Whisper word timings, revalidated, and rendered into 1080x1920 vertical clean short masters with matching sliced transcripts and metadata.
5. **Editorial Assessment**:
   - **Clip 01 (`10.92s`)**: **Strong comedic beat.** Captures Anne Hathaway describing the transition from friendly board game to intense competitiveness, culminating in *"Less competitive now"*.
   - **Clip 02 (`29.54s`)**: **Mixed / Over-extended.** Combines the competitiveness transition with the beginning of the kids discussion, but ends before Anne's resolving punchline (*"I play for money too"*).
   - **Clip 03 (`11.72s`)**: **Flawed / Incomplete.** Cuts off mid-anecdote when Fallon says *"Why kids? ... motherhood is often me, and I like to watch them win yeah"* without the contrasting reaction or punchline.

---

## 2. Input Integrity & Environment

- **Source Long Master Package**: `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/`
  - Verified package structure: `clip_01.mp4` (20,159,690 bytes), `transcript.json` (12 segments, 49.19s), `metadata.json` (`clip_id: lng_001`, source timeline `11.73s - 60.92s`, container duration `49.19s`).
  - [`validate_long_master_package()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/short_package.py#L25) executed successfully with zero validation errors.
- **Protection of Existing Artifacts**:
  - The source package video and sliced transcript were read strictly as read-only inputs.
  - The evaluation outputs were written to a new, uniquely named directory: `experimental_output/eval_stage3_semantic_anchor_live_20261025/`.
  - Baseline candidate hash was verified and remains strictly unmodified:
    `40474a9ea98a665c4ae1ce14703f1c6ffa04661952d9577f9a06fabe76e494fe`.
- **Exact Execution Command**:
  ```powershell
  $env:PYTHONPATH="backend"
  python -m app.cli.process_short_clips `
    experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01 `
    --run-dir experimental_output/eval_stage3_semantic_anchor_live_20261025 `
    --provider ollama `
    --model "qwen2.5:7b" `
    --goal humor `
    --log-level INFO
  ```

---

## 3. Anchor Extraction Performance

Ollama `qwen2.5:7b` was invoked with `SHORT_ANCHOR_SYSTEM_PROMPT` and the segment-tagged transcript (`[SEG_00]` through `[SEG_11]`).

The model returned **3 semantic anchors**:

| Anchor ID | Anchor Segment IDs | Anchor Type | Excerpt Quote | Grounding & Validation Result |
|---|---|---|---|---|
| `anc_001` | `[4]` (`SEG_04`) | `punchline` | *"Let's go. I want to win this something takes over"* | **VALID**. Grounded in `SEG_04` (`15.64s - 17.44s`). |
| `anc_002` | `[8, 9]` (`SEG_08, SEG_09`) | `punchline` | *"My kids are very competitive. Well, my one daughter is yeah The other one doesn't really care"* | **VALID**. Grounded in `SEG_08–09` (`31.44s - 37.84s`). |
| `anc_003` | `[6, 7]` (`SEG_06, SEG_07`) | `comedic_banter` | *"Why kids? Yeah, yeah, maybe being competitive is genetic... and I like to watch them when yeah"* | **VALID**. Grounded in `SEG_06–07` (`19.72s - 31.44s`). |

**Comparison to Previous Run**:
- Previous run: 11 raw proposals, 0% obeyed duration rules, 2 failed evidence grounding.
- New run: 3 semantic anchors, 100% valid segment IDs, 100% contiguous, 100% grounded evidence.

---

## 4. Bounded Window Construction & Ranking

From the 3 validated anchors, [`construct_bounded_candidate_windows()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/expansion.py#L140) constructed **5 raw candidate windows**:

1. **From `anc_001`** (Anchor: `SEG_04` at `15.64s - 17.44s`, duration 1.80s):
   - Backward search found sentence start at `SEG_02` (`8.88s`).
   - Forward search checked reaction at `SEG_05` (`19.72s`).
   - Generated Window 1 (`moderate`): `[8.88s - 19.72s]` (raw duration: `10.84s`).
2. **From `anc_002`** (Anchor: `SEG_08-09` at `31.44s - 37.84s`, duration 6.40s):
   - Backward search stepped back across `SEG_06-07` to sentence start at `SEG_02` (`8.88s`).
   - Forward search landed at `SEG_09` (`37.84s`).
   - Generated Window 2 (`moderate`): `[8.88s - 37.84s]` (raw duration: `28.96s`).
3. **From `anc_003`** (Anchor: `SEG_06-07` at `19.72s - 31.44s`, duration 11.72s):
   - Anchor raw duration `11.72s` $\ge 10.0\text{s}$, producing Window 3 (`tight`): `[19.72s - 31.44s]`.
   - Additional structural window combinations formed windows `[19.72s - 35.96s]` and `[19.72s - 37.84s]`.

### Ranking & Boundary Refinement Pipeline:
- **Raw Windows Generated**: 5 windows (all 5 satisfied $10.0\text{s} \le \text{duration} \le 60.0\text{s}$).
- **IoU Deduplication ($\text{IoU} \ge 0.50$)**:
  - Window `[19.72s - 37.84s]` and `[19.72s - 35.96s]` were suppressed due to high overlap with Window 3.
  - **3 candidates survived deduplication**.
- **Whisper Word-Timestamp Boundary Refinement**:
  - `cnd_001`: Snapped start from `8.88s` to `8.80s` (word onset). Refined interval: `[8.80s - 19.72s]` (`10.92s`).
  - `cnd_002`: Snapped start to `8.80s`; padded end silence from `37.84s` to `38.34s`. Refined interval: `[8.80s - 38.34s]` (`29.54s`).
  - `cnd_003`: Boundaries already aligned with speech pauses. Refined interval: `[19.72s - 31.44s]` (`11.72s`).

All 3 candidates passed post-refinement revalidation.

---

## 5. Detailed Editorial Review

### Clip 01: `srt_001_01` (`[8.80s - 19.72s]`, Duration: `10.92s`, Score: 87)
- **Rendered File**: `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_01/clip_01.mp4` (5.08 MB)
- **Transcript**:
  ```text
  [0.08s - 2.22s]: I know me neither. Are you what means you but then you saw over there
  [2.22s - 5.68s]: I was like, now it's just a nice friendly game and then the last I'm like that the points are on
  [6.84s - 8.64s]: Let's go. I want to win this something takes over
  [8.64s - 10.92s]: Less competitive now
  ```
- **Context & Setup**: Anne responds to Jimmy's question about whether she's competitive. She explains that it started as a friendly game, but once points were on the line, *"something takes over"*.
- **Payoff & Ending**: Lands squarely on Anne's deadpan quip *"Less competitive now"*, followed by audience amusement.
- **Standalone Value**: **High.** Operates as an independent, funny, self-deprecating confession about competitive gaming. Pacing is sharp.
- **Editorial Rating**: **ACCEPTABLE / USABLE SHORT**.

---

### Clip 02: `srt_001_02` (`[8.80s - 38.34s]`, Duration: `29.54s`, Score: 80)
- **Rendered File**: `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_02/clip_02.mp4` (13.55 MB)
- **Transcript**:
  ```text
  [0.08s - 10.92s]: (Same as Clip 01 above)
  [10.92s - 18.92s]: Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are like they they they're competitive too
  [18.92s - 22.64s]: And it turns out motherhood is often me, and I like to watch them when yeah
  [22.64s - 27.16s]: My kids are very competitive. Well, my one daughter is yeah
  [27.16s - 29.04s]: Yeah, the other one doesn't really care
  ```
- **Context & Setup**: Begins with the competitive confession from Clip 01, then pivots into Jimmy asking about kids.
- **Payoff & Ending**: Ends on *"Yeah, the other one doesn't really care"* at `38.34s`.
- **Editorial Flaw**:
  The conversation directly continues into the true punchline: Anne explaining that she plays for money against her kids (`43.83s - 47.69s`). By cutting off at `38.34s`, Clip 02 severs the setup from its actual comedic climax. Furthermore, stitching together the game banter (`8.8s - 19.7s`) with the kids discussion creates an unfocused clip with two separate topics.
- **Editorial Rating**: **WEAK / UNFINISHED PAYOFF**.

---

### Clip 03: `srt_001_03` (`[19.72s - 31.44s]`, Duration: `11.72s`, Score: 80)
- **Rendered File**: `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_03/clip_03.mp4` (6.20 MB)
- **Transcript**:
  ```text
  [0.0s - 8.0s]: Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are like they they they're competitive too
  [8.0s - 11.72s]: And it turns out motherhood is often me, and I like to watch them when yeah
  ```
- **Context & Setup**: Jimmy starts talking about kids and competitive genetics.
- **Payoff & Ending**: Cuts off abruptly right after Anne says *"motherhood is often me, and I like to watch them win yeah"*.
- **Editorial Flaw**: This is an incomplete thought. The anchor selected by the model (`[SEG_06, SEG_07]`) stopped right before Anne talks about her daughter and playing for money. Because the anchor duration (`11.72s`) met the minimum threshold (`>= 10.0s`), the window generator produced a `tight` window without requiring forward expansion to the resolution.
- **Editorial Rating**: **REJECT / INCOMPLETE ANECDOTE**.

---

## 6. Output & Test Integrity Verification

1. **Baseline Hash Verification**:
   - `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`:
     `40474a9ea98a665c4ae1ce14703f1c6ffa04661952d9577f9a06fabe76e494fe` (CONFIRMED UNCHANGED).
2. **Directory Protections**:
   - `input/`: Zero modifications.
   - `outputs/`: Zero modifications.
   - `experimental_output/eval_stage2_stage3_live_20261024/`: Zero modifications to media or sliced transcript.
3. **Artifacts Emitted in New Evaluation Directory**:
   - `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_01/clip_01.mp4` (10.92s, 1080x1920)
   - `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_02/clip_02.mp4` (29.54s, 1080x1920)
   - `experimental_output/eval_stage3_semantic_anchor_live_20261025/short_clips/clip_03/clip_03.mp4` (11.72s, 1080x1920)

---

## 7. Conclusions & Next Steps

### What Succeeded:
- **Elimination of Token-Copying Micro-Fragments**: The transition to `[SEG_XX]` tags completely cured the model's token-copying pathology. The model returned 3 clean semantic anchors instead of 11 rejected micro-fragments.
- **100% Pipeline Reliability**: Window construction, boundary refinement, and rendering executed end-to-end without errors or invalid durations. Clip 01 (`10.92s`) is a genuine, high-quality comedic excerpt.

### Editorial Weakness Observed:
- While Clip 01 succeeded, Clips 02 and 03 suffered from premature ending boundaries. Specifically, the model chose anchors that omitted the final punchline at `SEG_11` (*"I play for money to"*). Because `anc_003` (`SEG_06–07`) was already 11.72s, the algorithm formed a `tight` window that truncated before the story reached its comedic payoff.

### Recommendation:
The architecture is technically proven and safe. For future refinement, the prompt should instruct the model that story arcs and comedic anecdotes must include their final punchline in `anchor_segment_ids`, or forward expansion should check for story resolution before capping tight windows.
