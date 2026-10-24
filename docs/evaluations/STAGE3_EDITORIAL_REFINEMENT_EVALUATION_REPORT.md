# Stage 3 Editorial Refinement — Controlled Live Evaluation Report

**Evaluation Date**: 2026-10-25  
**Model & Provider**: Ollama `qwen2.5:7b` (local instance at `http://localhost:11434`)  
**Editorial Goal**: `humor`  
**Execution Pipeline**: Stage 3 Standalone Short-Clip Pipeline  
**Source Long-Master Package**: `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/`  
**Parent Video Media**: `clip_01.mp4` (Duration: `49.19s`, Size: 20,159,690 bytes)  
**Parent Sliced Transcript**: `transcript.json` (12 segments, 176 words)  
**Evaluation Output Directory**: `experimental_output/eval_stage3_editorial_refinement_live_20261025/`  

---

## 1. Executive Summary & Verdict

### **Overall Verdict: EDITORIAL MIXED**

- **Technical Execution**: **100% PASS**.
  - Anchor extraction, bounded window expansion, ranking, boundary refinement, and rendering completed without failure.
  - Zero validation rejections.
  - 3 clean vertical masters (1080x1920) rendered with matching sliced transcripts and metadata.
- **Editorial Quality**: **MIXED**.
  - **Clip 01 (`10.92s`)**: **EDITORIAL PASS (EXCELLENT)**. The standalone reverse-charades confession (*"Let's go. I want to win this something takes over... Less competitive now"*) remains fully preserved, tightly paced, and punchy.
  - **Clip 02 (`29.54s`)**: **EDITORIAL FAIL (OVER-STITCHED)**. Merges the charades confession with the kids discussion across the topic shift at `SEG_06` (*"Why kids?"*), ending abruptly before the concluding money punchline.
  - **Clip 03 (`12.39s`)**: **EDITORIAL PASS (SUBSTANTIAL IMPROVEMENT OVER PREVIOUS RUN)**. Replaces the incomplete anecdote of the prior evaluation (`19.72s - 31.44s`, which broke mid-sentence on *"motherhood is often me..."*) with a coherent, self-contained comedic beat (`31.44s - 43.83s`): Anne describing her daughter's intense competitiveness and concluding: *"the other one really wants to win and I don't I don't throw the games"*.

---

## 2. Environment, Configuration & Exact Command

### Exact CLI Command Executed:
```powershell
$env:PYTHONPATH="backend"
python -m app.cli.process_short_clips `
  experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01 `
  --run-dir experimental_output/eval_stage3_editorial_refinement_live_20261025 `
  --provider ollama `
  --model "qwen2.5:7b" `
  --goal humor `
  --log-level INFO
```

### Settings & Boundaries:
- `min_duration_seconds`: `10.0`
- `max_duration_seconds`: `60.0`
- `target_duration_seconds`: `30.0`
- `candidate_pool_target`: `10`
- `display_limit`: `10`
- `iou_threshold`: `0.50`
- Media source bounds: `0.0s - 49.19s` (Local), corresponding to source parent range `11.73s - 60.92s`.

---

## 3. Discovered Anchors & Raw Window Expansion

In this run, Ollama `qwen2.5:7b` returned 3 semantic anchors referencing chunk segments:
1. `anc_001`: `[SEG_04]` (`15.64s - 17.44s`) — *"Let's go. I want to win this something takes over"*
2. `anc_002`: `[SEG_06, SEG_07]` (`19.72s - 31.44s`) — *"Why kids? ... motherhood is often me, and I like to watch them when yeah"*
3. `anc_003`: `[SEG_10]` (`38.39s - 43.83s`) — *"Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games"*

Across these anchors, candidate expansion generated 5 valid raw windows:
- From `anc_001`: `[8.88s - 19.72s]` (moderate)
- From `anc_002`: `[8.88s - 38.34s]` (moderate)
- From `anc_003`: `[31.44s - 43.83s]` (fallback_nearest)
- Plus alternative combinations filtered by target proximity and IoU deduplication.

Zero anchors were rejected for malformed IDs or hallucinated text.

---

## 4. Rendered Clips & Editorial Review

### Clip 01: `srt_001_01`
- **Rendered File**: `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_01/clip_01.mp4` (5.08 MB)
- **Local Timeline**: `8.80s - 19.72s` (Duration: `10.92s`)
- **Parent Source Video Timeline**: `20.53s - 31.45s` (`0:20.53 - 0:31.45`)
- **Overall Score**: `87`
- **Transcript**:
  > *"know me neither. you what means you but then you saw over there I was like, now it's just a nice friendly game and then the last I'm like that the points are on Let's go. I want to win this something takes over Less competitive now"*
- **Editorial Analysis**:
  - **Hook**: Anne admitting to getting competitive in charades.
  - **Payoff**: Lands cleanly on *"Less competitive now"* with deadpan comedic delivery.
  - **Coherence**: Highly coherent, self-contained, standalone comedic beat.
  - **Verdict**: **EDITORIAL PASS (STRONG SHORT)**.

---

### Clip 02: `srt_001_02`
- **Rendered File**: `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_02/clip_02.mp4` (13.55 MB)
- **Local Timeline**: `8.80s - 38.34s` (Duration: `29.54s`)
- **Parent Source Video Timeline**: `20.53s - 50.07s` (`0:20.53 - 0:50.07`)
- **Overall Score**: `80`
- **Transcript**:
  > *"know me neither. you what means you but then you saw over there I was like, now it's just a nice friendly game and then the last I'm like that the points are on Let's go. I want to win this something takes over Less competitive now Why kids? yeah, maybe being competitive is genetic because my kids are like they they they're competitive too And it turns out motherhood is often me, and I like to watch them when yeah My kids are very competitive. Well, my one daughter is yeah Yeah, the other one doesn't really care"*
- **Editorial Analysis**:
  - **Structure**: Combines two separate conversational topics: the friendly charades game confession (`8.80s - 19.72s`) and Jimmy's pivot into kids (`19.72s - 38.34s`).
  - **Editorial Flaw**: It stops at `38.34s` (*"the other one doesn't really care"*), cutting off right before Anne reveals how the competitive daughter wants to win and that Anne doesn't throw the games (`SEG_10`) and plays for money (`SEG_11`).
  - **Root Cause**: The model generated `anc_002` covering `[SEG_06, SEG_07]`. The backward search traversed prior segments. Even though `TOPIC_TRANSITION_PATTERNS` contains `"why kids"`, `SEG_06` text begins with `"Why kids? Yeah, yeah..."` and backward search stepped back into `SEG_05`.
  - **Verdict**: **EDITORIAL FAIL (OVER-STITCHED / PREMATURE CLIMAX)**.

---

### Clip 03: `srt_001_03`
- **Rendered File**: `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_03/clip_03.mp4` (4.16 MB)
- **Local Timeline**: `31.44s - 43.83s` (Duration: `12.39s`)
- **Parent Source Video Timeline**: `43.17s - 55.56s` (`0:43.17 - 0:55.56`)
- **Overall Score**: `80`
- **Transcript**:
  > *"My kids are very competitive. Well, my one daughter is yeah Yeah, the other one doesn't really care Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games"*
- **Editorial Analysis**:
  - **Comparison with Previous Run**: In the previous evaluation, Clip 03 was `19.72s - 31.44s` (`11.72s`), which ended abruptly on *"motherhood is often me, and I like to watch them when yeah"*—an unusable fragment.
  - **Current Run Outcome**: In this run, the third candidate shifted to `31.44s - 43.83s` (`12.39s`). This captures Anne contrasting her two daughters and landing firmly on: *"the other one really wants to win and I don't I don't throw the games"*.
  - **Standalone Value**: Coherent, comedic, and delivers a complete conversational thought about parenting and competitive games.
  - **Verdict**: **EDITORIAL PASS (USABLE SHORT)**.

---

## 5. Evaluation Questions Answered

### 1. Does the standalone charades confession remain coherent and usable?
**Yes.** Clip 01 (`8.80s - 19.72s`, `10.92s`) was reproduced cleanly, maintaining its setup, transition, and punchline (*"Less competitive now"*).

### 2. Does the kids anecdote produce a candidate that includes the actual resolution, including the later money-related punchline where appropriate?
**Partially.**
- Clip 03 successfully reached `SEG_10` (`43.83s`), resolving with *"the other one really wants to win and I don't I don't throw the games"*.
- However, neither Clip 02 nor Clip 03 extended through `SEG_11` (`43.83s - 47.69s`, *"I play for money too"*). This occurred because Qwen2.5:7b proposed anchors up through `SEG_10` (`anc_003`), but did not select `SEG_11` as an anchor segment. Forward expansion from `SEG_10` reached `43.83s` which was already a terminal punctuation boundary with complete duration (`12.39s`), so it halted without requiring `SEG_11`.

### 3. Are incomplete prefixes still selected ahead of better-resolved alternatives?
**No.** The previous truncated prefix `19.72s - 31.44s` was completely eliminated from the top 3 ranked candidates. It was replaced by `31.44s - 43.83s`, which has a resolved punchline.

### 4. Does backward expansion avoid combining unrelated conversational beats?
**Not completely.** While Clip 01 and Clip 03 are tightly focused single-topic beats, Clip 02 (`8.80s - 38.34s`) still stitched the charades discussion with the kids discussion. This demonstrates that regex-based topic cues on transcripts are an imperfect proxy when the model anchors a segment immediately following a topic shift.

### 5. Does endpoint-preserving NMS retain useful alternatives without allowing redundant or over-extended clips to dominate?
**Yes.** The candidate pool produced distinct, non-overlapping moments (Clip 01 at `8.8s - 19.7s`, Clip 03 at `31.4s - 43.8s`), while Clip 02 represents a longer narrative attempt. No redundant micro-variants dominated the selection.

### 6. Are all final candidates within duration and parent-media bounds, with successful boundary refinement, validation, and rendering?
**Yes.** All 3 clips:
- Are strictly within $[10.0\text{s}, 60.0\text{s}]$: `10.92s`, `29.54s`, and `12.39s`.
- Are strictly within parent media duration (`49.19s`).
- Word timestamps successfully refined start and end cuts at natural speech boundaries.
- Rendered valid vertical MP4 clean masters (1080x1920) with synchronized transcripts.

---

## 6. Output & Test Integrity Verification

1. **Baseline Hash Verification**:
   - `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`:
     `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (**CONFIRMED UNCHANGED**).
2. **Protected Directories**:
   - `input/`: Zero modifications.
   - `outputs/`: Zero modifications.
   - `experimental_output/eval_stage2_stage3_live_20261024/`: Zero modifications to media or sliced transcript.
   - `experimental_output/eval_stage3_semantic_anchor_live_20261025/`: Zero modifications.
3. **Artifacts Emitted in New Evaluation Directory**:
   - `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_01/clip_01.mp4` (10.92s, 1080x1920)
   - `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_02/clip_02.mp4` (29.54s, 1080x1920)
   - `experimental_output/eval_stage3_editorial_refinement_live_20261025/short_clips/clip_03/clip_03.mp4` (12.39s, 1080x1920)
