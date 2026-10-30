# Investigation Report: Long-Clip Quantity Reduction and Short-Clip Narrative Quality

**Date:** October 30, 2026  
**Target Run:** [`run_002_090552`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/outputs/2026-10-29/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264_/run_002_090552/)  
**Model & Adapter:** `qwen2.5:7b` via Ollama (`num_predict=4096`, `temperature=0.3`)  
**Transcript Evaluated:** Anne Hathaway & Jimmy Fallon (*The Tonight Show*, 334 segments, 2,039 words)

---

## 1. Baseline Clarification: Location of the "3 Long Clips" Baseline

A systematic search across `outputs/`, `experimental_output/`, and `docs/evaluations/` established the following:

- **No automated full-pipeline run ever rendered 3 long clips.**
- The historical memory of "3 long clips" originates from **Phase 2 manual ground-truth evaluation**:
  - In [`docs/evaluations/PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/evaluations/PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md), the team manually extracted three 16:9 benchmark moments in [`outputs/experiments/first_three_minutes/`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/outputs/experiments/first_three_minutes/):
    1. **Moment A** (`11.73s – 60.92s`, 49.19s): *Competitive Parenting / Kids' milestones*
    2. **Moment B** (`83.92s – 118.74s`, 34.82s): *The Devil Wears Prada trivia confusion*
    3. **Moment C** (`131.78s – 186.26s`, 54.48s): *The Princess Diaries fan catchphrase*
  - These 3 long clips were manually sliced by human evaluators specifically because the automated candidate discovery in Phase 2 failed to capture them as coherent 30s+ segments.
- Furthermore, the historical run that rendered **3 clips** was **Stage 3 Shorts Rendering** ([`docs/evaluations/STAGE3_TOPIC_ISOLATION_LIVE_EVALUATION_20261025.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/evaluations/STAGE3_TOPIC_ISOLATION_LIVE_EVALUATION_20261025.md)), which rendered **3 short clips from a single packaged long clip** (`clip_01`).
- The automated Stage 2 benchmark run from October 24 ([`experimental_output/long_clip_discovery_qwen25_humor_20261024/candidates.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/experimental_output/long_clip_discovery_qwen25_humor_20261024/candidates.json)) **also accepted only 1 long candidate** (`cnd_001`, 31.33s) and rejected 9 candidates for duration below 30s.

---

## 2. Side-by-Side Comparison: Oct 24 Benchmark vs. Run 002

| Dimension | Oct 24 Benchmark (`experimental_output/.../long_clip_discovery_qwen25_humor_20261024`) | Latest Full Pipeline (`run_002_090552`) |
| :--- | :--- | :--- |
| **Pipeline Stage** | Stage 2 Isolated Discovery | Full Pipeline (Transcription reused $\to$ Stage 2 $\to$ Stage 3 $\to$ Rendering) |
| **Input Chunks** | 2 chunks (`chunk_001` [0–270s], `chunk_002` [210–480s]) | 2 chunks (`chunk_001` [0–270s], `chunk_002` [210–480s]) |
| **Requested Target** | 5 per chunk (Total target: 10) | 3 per chunk (Total target: 4 via `long_candidate_pool_target`) |
| **Total Raw Proposed** | 10 raw candidates (5 from Chunk 1, 5 from Chunk 2) | 6 raw candidates (3 from Chunk 1, 3 from Chunk 2) |
| **Accepted Candidates** | **1** (`cnd_001`, duration 31.33s) | **1** (`cnd_001`, duration 47.79s) |
| **Rejected Candidates** | **9** rejected (`DURATION_BELOW_MINIMUM` < 30.0s) | **5** rejected (`DURATION_BELOW_MINIMUM` < 30.0s) |
| **Accepted Topic** | *The Idea of You* synopsis (`385.17s – 416.50s`) | *Shakespeare in the Park Delacorte story* (`256.58s – 304.37s`) |
| **Rendered Long Clips** | None (discovery only) | **1** (`long_clips/clip_01/clip_01.mp4`) |
| **Rendered Shorts** | None (discovery only) | **2** (`clip_01_short_01.mp4`, `clip_01_short_02.mp4`) |

---

## 3. Root Cause of Long-Clip Quantity Reduction

Why did `run_002_090552` only accept 1 long candidate?

### Raw Candidate Inspection in `run_002_090552`

Inspecting [`outputs/2026-10-29/.../run_002_090552/candidates.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/outputs/2026-10-29/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264_/run_002_090552/candidates.json):

1. **Raw Proposal 1** (`31.41s – 57.12s`, **25.71s**):  
   - *Status*: **Rejected** (`DURATION_BELOW_MINIMUM`, min=30.0s).  
   - *Content*: **Moment A** (Competitive parenting / Jimmy Fallon and Anne comparing children's reading).  
   - *Ground Truth Span*: `11.73s – 60.92s` (49.19s). The model accurately found the core joke, but set boundaries too tight (25.71s), falling 4.29s short of the threshold.
2. **Raw Proposal 2** (`90.46s – 118.42s`, **27.96s**):  
   - *Status*: **Rejected** (`DURATION_BELOW_MINIMUM`, min=30.0s).  
   - *Content*: **Moment B** (*The Devil Wears Prada* trivia confusion).  
   - *Ground Truth Span*: `83.92s – 118.74s` (34.82s). The model captured the punchline but omitted the 7-second setup, resulting in 27.96s (just 2.04s short of the threshold).
3. **Raw Proposal 3** (`360.97s – 382.61s`, **21.64s**):  
   - *Status*: **Rejected** (`DURATION_BELOW_MINIMUM`, min=30.0s).  
   - *Content*: Raccoons arriving on stage at the Delacorte Theater.
4. **Raw Proposal 4** (`385.17s – 408.82s`, **23.65s**):  
   - *Status*: **Rejected** (`DURATION_BELOW_MINIMUM`, min=30.0s).  
   - *Content*: *The Idea of You* book synopsis. In Oct 24, the model proposed `385.17s – 416.50s` (31.33s); in this run, it curtailed the tail end by 7.7s.
5. **Raw Proposal 5** (`457.52s – 464.92s`, **7.40s**):  
   - *Status*: **Rejected** (`DURATION_BELOW_MINIMUM`, min=30.0s).  
   - *Content*: Brief closing remark.
6. **Raw Proposal 6** (`256.58s – 304.37s`, **47.79s**):  
   - *Status*: **Accepted as `cnd_001`**.  
   - *Content*: Shakespeare in the Park conversation.

### Primary Drivers
1. **Model Bias Toward Micro-Conversations (20–28s)**:  
   `qwen2.5:7b` consistently identifies high-signal comedic moments (Moments A, B, and the book synopsis), but its window boundary prediction tends to tightly frame only the punchline exchange rather than the narrative setup + punchline context.
2. **Hard Minimum Duration Wall (30.0s)**:  
   Because [`candidate_scoring.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/candidate_scoring.py#L384-L390) enforces `duration >= 30.0s` as an uncompromising rejection rule without a soft tolerance or expansion window, candidates of 27.96s (Moment B) and 25.71s (Moment A) are unconditionally discarded.
3. **Lower Per-Chunk Candidate Target (3 instead of 5)**:  
   With `long_candidate_pool_target=4` (derived target = 3 per chunk), only 3 candidates are elicited per chunk. When the model proposes 20–28s spans for all of them except one, only 1 long candidate survives filtering.

---

## 4. Root Cause of the Abrupt Long-Clip Ending

In [`outputs/.../run_002_090552/long_clips/clip_01/clip_01.mp4`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/outputs/2026-10-29/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264_/run_002_090552/long_clips/clip_01/clip_01.mp4), the clip starts cleanly, discusses Shakespeare in the Park, but cuts off abruptly at `304.37s` before any narrative resolution.

### The Forensic Evidence
Examining [`candidates.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/outputs/2026-10-29/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264_/run_002_090552/candidates.json#L77-L101):
```json
{
  "start_seconds": 256.88,
  "end_seconds": 303.94,
  "hook": "Anne Hathaway recounts a hilarious story about a family of raccoons interrupting a Shakespeare in the park performance.",
  "rationale": "Humorous and relatable story with a surprising twist involving raccoons...",
  "transcript_excerpt": "Behind you, as soon as you came on stage, a family of raccoons came out... high-fived to the raccoons."
}
```

### Divergence Analysis
1. **The Model's Intent vs. Timestamp Selection**:  
   The model's `hook`, `rationale`, and `transcript_excerpt` clearly show it intended to select the entire raccoon anecdote (which runs from segment `seg_000174` [256.88s] through `seg_000257` [382.61s]).
2. **Intermediate Timestamp Selection**:  
   Instead of outputting `end_seconds: 382.61`, the model selected `end_seconds: 303.94`.  
   In the transcript:
   - `[300.20s – 303.94s]`: Jimmy Fallon says *"and the whole show was so joyful."*
   - `[304.42s – 308.82s]`: Anne Hathaway says *"I had such a wonderful time, but one night something... I don't know if it went wrong, but something happened."*
   The model erroneously latched onto the timestamp of the earlier pause (`303.94s`), cutting off the story **immediately before Anne began telling the raccoon incident**.
3. **Refinement Behavior**:  
   [`boundary_refinement.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/boundary_refinement.py) refined `[256.88s – 303.94s]` to the sentence boundary `[256.58s – 304.37s]`. Boundary refinement only performs micro-adjustments around sentence edges; it is not designed to expand a proposed window by 78 seconds.

---

## 5. Narrative Completeness of Short 1 vs. Short 2

Both shorts were extracted from `clip_01` (`256.58s – 304.37s`).

### Short 2 (`2.14s – 13.35s` of long clip / `258.72s – 269.93s` source timeline, 11.21s)
- **Why it worked well**:
  - **Dialogue**:  
    - Jimmy: *"I've never done Shakespeare in the park, by the way. I've never been asked."*  
    - Anne: *"Well..."*  
    - Jimmy: *"No, but you're like, 'Well, maybe one day.'"* (Laughter).
  - **Structure**: Complete call-and-response comedic beat with an opening premise, tease, reaction, and punchline within 11.21s. It is self-contained.

### Short 1 (`10.10s – 22.23s` of long clip / `266.68s – 278.81s` source timeline, 12.13s)
- **Why it felt incomplete and abrupt**:
  - **Dialogue**:  
    - Jimmy: *"No, but you're like, 'Well, maybe one day.' But you were amazing. I saw you in Twelfth Night."*  
    - Anne: *"Thank you."*  
    - Jimmy: *"Do you get nervous doing that? It's outside, Delacorte Theater."*
    - **Cut!**
  - **Root Cause**:
    - Stage 3 short discovery (`topic_isolation.py`) identified the anchor `"You were amazing."`
    - Because the anchor lacked a full extracted sequence, it invoked [`fallback_nearest`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/topic_isolation.py) / bounded window expansion to construct a 12-second window around that anchor.
    - The window captured Jimmy asking the question (*"Do you get nervous doing that?"*), but cut off before Anne's answer. The pipeline does not currently enforce a Q&A completion check or conversational turn resolution on short candidate windows.

---

## 6. Assessment of Short 2 Quality Against Product Standards

Short 2 demonstrates the target baseline for conversational short clips:
- **Hook Speed**: The premise starts at 0.0s (*"I've never done Shakespeare in the park..."*).
- **Turn Density**: 3 alternating speaker turns in 11.2 seconds.
- **Narrative Closure**: The interaction resolves on the audience laugh track at 13.35s.
- **Missing Elements**:
  - Vertical reframing / face tracking (currently center-cropped).
  - Dynamic burned-in word captions.

---

## 7. Prioritized Recommended Implementation Changes

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PRIORITIZED ROADMAP                             │
├────────────────────────────────────────────────────────────────────────┤
│ 1. P0: Narrative Boundary Expansion for Long-Mode Discovery            │
│    - Allow boundary refinement to extend sub-30s high-scoring          │
│      candidates (e.g., 25-29s) to complete speaker turns up to min-dur │
│    - Recover Moments A (25.71s) and B (27.96s) automatically           │
├────────────────────────────────────────────────────────────────────────┤
│ 2. P0: Prompt & Schema Guidance for Arc Completion                     │
│    - Update long-mode system prompt with strict rule:                  │
│      "Ensure end_seconds aligns with the conclusion of the story,      │
│       not the transition or setup question."                           │
├────────────────────────────────────────────────────────────────────────┤
│ 3. P1: Conversational Turn Closure in Short Extraction (Stage 3)       │
│    - In `topic_isolation.py`, ensure window does not terminate         │
│      immediately after an unresolved question mark (`?`).              │
├────────────────────────────────────────────────────────────────────────┤
│ 4. P1: Dynamic Per-Chunk Target Scaling                                │
│    - When long discovery is run with 2 chunks, calibrate target        │
│      (e.g., target 4 per chunk, requesting 8 candidates total)         │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Long Candidate Tolerance & Expansion Window (P0)**:
   - Rather than dropping candidates between 22s and 29.9s, allow [`boundary_refinement.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/boundary_refinement.py) to look outward to the nearest preceding/following sentence boundaries to reach the 30.0s threshold if narrative cohesion score is high.
2. **Long-Mode Prompt Enforcement for Timestamps (P0)**:
   - Enhance [`candidate_discovery.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/candidate_discovery.py) prompt to explicitly require that `end_seconds` match the final timestamp of the `transcript_excerpt`.
3. **Stage 3 Question-Resolution Boundary Guard (P1)**:
   - In [`topic_isolation.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/pipeline/topic_isolation.py), add a guard preventing a short candidate window from terminating on a sentence ending with `?` without including the subsequent turn.

---

## 8. Validation Test Plan

To validate these changes without rerunning full transcription:
1. **Isolated Long Discovery Test**:
   - Run `backend/app/cli/discover_candidates.py` on the cached transcript with boundary expansion enabled.
   - Assert `accepted_count >= 2` (confirming Moments A and B are accepted).
2. **Timestamp Alignment Unit Test**:
   - Add unit test verifying that parsed candidate `end_seconds` covers the segments cited in `transcript_excerpt`.
3. **Stage 3 Short Boundary Unit Test**:
   - Add test with transcript containing a question at 11s and answer at 15s; verify short window includes the answer.
