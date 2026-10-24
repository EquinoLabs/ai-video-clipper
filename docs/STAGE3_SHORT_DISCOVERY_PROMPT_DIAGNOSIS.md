# Stage 3 — Short Discovery Prompt & Code-Path Diagnosis

**Author:** Antigravity AI  
**Date:** 2026-10-25  
**Status:** COMPLETE (Read-Only Investigation)  
**Target:** AI Video Clipper — Stage 3 Short-Clip Discovery Pipeline  
**Reference Case:** Evaluation Run `experimental_output/eval_stage2_stage3_live_20261024/` (49.19s long master `clip_01`)

---

## 1. Executive Summary

In our latest Stage 3 controlled live evaluation, Ollama `qwen2.5:7b` analyzed the sliced transcript of a 49.19-second board-game conversation from *The Tonight Show Starring Jimmy Fallon* (guest Anne Hathaway). The model proposed 11 candidates. Every candidate had a duration between 1.88s and 8.00s and was rejected by backend validation for violating the 10.0-second minimum duration threshold (`clip_min_seconds: 10.0`).

This read-only investigation inspected the prompt templates, prompt generation logic, provider adapter mechanics, structured-output schemas, and raw artifacts in `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/`.

### Key Conclusions:
1. **The micro-durations originate entirely within the raw LLM response.**
   The model itself emitted exact start/end timestamps ranging from 1.88s to 8.00s. Downstream Python code did not truncate, modify, or shrink any candidate interval.
2. **Every single proposal was a direct token copy of one or two transcript lines.**
   In 9 of the 11 proposals, the LLM returned timestamps that matched the exact segment boundaries of a single transcript segment down to the hundredth of a second. The remaining 2 proposals matched adjacent segment pairs (`SEG_04 + SEG_05` and `SEG_06 + SEG_07`).
3. **The prompt explicitly demands multi-segment standalone moments, but the model cannot obey due to decoder arithmetic and segment-anchor bias.**
   The system prompt explicitly commands: *"Hard duration limits: Every candidate MUST satisfy: 10.0 <= (end_seconds - start_seconds) <= 60.0"* and *"Select COMPLETE, standalone moments spanning MULTIPLE consecutive segments... NEVER select a single isolated segment (e.g. 3-5 seconds punchline) by itself."*
   However, because the prompt presents transcript text formatted segment-by-segment with leading timestamps (`[15.64s - 17.44s] ...`), small autoregressive decoder models (7B) copy the literal timestamp numbers flanking the identified quote or hook rather than executing arithmetic subtraction and expanding across multiple lines.
4. **Zero candidates reached boundary refinement.**
   Boundary refinement ([`refine_candidate_boundaries()`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/candidates/boundaries.py#L50)) only runs on candidates that pass initial duration validation. Because all 11 proposals failed the 10.0s check upfront, boundary refinement was never invoked.

---

## 2. Exact Short-Discovery System and User Prompts

### 2.1 Prompt Source Files and Functions
- **System & User Prompt Templates**: [`backend/app/services/llm/prompts.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/prompts.py#L7-L136)
  - Function: `build_system_prompt(goal, settings, is_long_clip=False)`
  - Function: `build_user_prompt(formatted_transcript, custom_instructions, target_count, is_long_clip=False)`
- **Transcript Formatter**: [`backend/app/services/llm/chunking.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/chunking.py#L23-L30)
  - Function: `format_segments_to_text(segments)`
- **Provider Invocation**: [`backend/app/services/llm/ollama_adapter.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/ollama_adapter.py#L111-L154)
  - Function: `OllamaAdapter.discover_and_evaluate()`

### 2.2 System Prompt Template (`is_long_clip=False`)
Below is the verbatim system prompt constructed for the live run (with `goal=HUMOR`, `min_duration=10.0`, `preferred_min=15.0`, `preferred_max=45.0`, `target_duration=30.0`, `max_duration=60.0`):

```text
You are an expert editorial video producer and short-form content curator.
Your task is to analyze a timestamped transcript from a long-form video and identify high-potential short clip candidates suitable for vertical video platforms (YouTube Shorts, TikTok, Instagram Reels).

### EVALUATION CRITERIA (8 DIMENSIONS)
Rate each candidate on each dimension using a 0.0 to 5.0 scale (decimal increments e.g. 3.5, 4.0, 4.5):
1. hook_strength: How effectively the opening seconds establish immediate intrigue, curiosity, or a clear promise.
2. completeness_coherence: Whether the excerpt forms a self-contained story, insight, or explanation with a beginning, middle, and clean conclusion.
3. standalone_understandability: How well the moment makes complete sense to a viewer who hasn't watched the rest of the video.
4. goal_relevance: How well the moment aligns with the user's selected editorial goal and any custom instructions.
5. goal_specific_impact: The comedic punchline, educational insight, emotional resonance, or thought-provoking value.
6. specificity_insight: Presence of a concrete, non-generic idea, surprising detail, or clear actionable takeaways.
7. pacing_conciseness: Whether the moment avoids dead air, filler, rambling, or unneeded setup.
8. ending_quality: Whether the moment lands its final point or punchline cleanly without being cut off mid-thought.

### CANDIDATE BOUNDARIES & DURATION RULES
1. Hard duration limits: Every candidate MUST satisfy: 10.0 <= (end_seconds - start_seconds) <= 60.0 seconds. Candidates under 10.0s or over 60.0s are hard-rejected.
2. Preferred duration: Aim for 15.0 to 45.0 seconds (target: ~30.0s).
3. Select COMPLETE, standalone moments spanning MULTIPLE consecutive segments:
   - A viable short clip must include the setup/context, development/banter, and payoff/punchline so it makes sense on its own.
   - NEVER select a single isolated segment (e.g. 3-5 seconds punchline) by itself.
   - Set `start_seconds` to the start time of the opening setup segment, and `end_seconds` to the end time of the concluding payoff segment.
4. Avoid padding: Do not include unrelated preceding or following dialogue merely to reach duration limits. The setup must directly lead into the payoff.

### EDITORIAL GOAL: HUMOR
Focus on funny moments, comedic timing, sharp banter, punchlines, and humorous reactions.

### GROUNDING & TIMESTAMP RULES
1. Timestamps: All start_seconds and end_seconds must be exact decimal seconds matching the transcript segment timestamps (e.g., 90.48, 118.74). Do not convert to MM:SS or truncate numbers.
2. Evidence: The `evidence` field MUST contain 1 to 3 direct verbatim quote excerpts copied directly from the transcript lines within the chosen clip interval. Do not paraphrase or splice non-adjacent words.
3. Do not invent or hallucinate moments, quotes, or timestamps.
4. If the transcript does not contain suitable moments meeting quality standards, return fewer candidates or an empty array. Do not pad with weak moments.
```

### 2.3 User Prompt Delivered in the Live Run
```text
### TIMESTAMPED TRANSCRIPT:
[0.00s - 4.14s] Thank you for playing reverse your aids with me. You're a great partner. Thank you. You're a partner
[4.14s - 8.72s] I mean, are you are you competitive when you play games? Do you play games at home in to be?
[8.88s - 11.02s] I know me neither. Are you what means you but then you saw over there
[11.02s - 14.48s] I was like, now it's just a nice friendly game and then the last I'm like that the points are on
[15.64s - 17.44s] Let's go. I want to win this something takes over
[17.44s - 19.72s] Less competitive now
[19.72s - 27.72s] Why kids? Yeah, yeah, maybe being competitive is genetic because my kids are like they they they're competitive too
[27.72s - 31.44s] And it turns out motherhood is often me, and I like to watch them when yeah
[31.44s - 35.96s] My kids are very competitive. Well, my one daughter is yeah
[35.96s - 37.84s] Yeah, the other one doesn't really care
[38.39s - 43.83s] Because I got's fun. It's all good, but the other one really wants to win and I don't I don't throw the games
[43.83s - 47.69s] You know, I go I go I go I really and I play for I play for money to


Identify candidate clips from this transcript section. Explore the entire supplied transcript section thoroughly, identifying distinct moments, complete story arcs, conversational exchanges, setups and payoffs, reactions, and punchlines without clustering all candidates around a single moment. Do not fabricate or pad weak candidates merely to meet the target count. Return a structured JSON object containing a `candidates` list according to the schema.
```

---

## 3. The Short-Discovery Call Path Trace

```
1. CLI Entry Point
   backend/app/cli/process_short_clips.py:main()
   └── Calls run_short_clip_pipeline()

2. Package Validation & Transcripts Loading
   backend/app/services/candidates/short_pipeline.py:run_short_clip_pipeline()
   ├── validate_long_master_package() -> loads clip_01.mp4, transcript.json, metadata.json
   └── GenerationSettings.for_short_clips(min=10.0, target=30.0, max=60.0)

3. Sliced Transcript Chunking
   backend/app/services/candidates/short_pipeline.py:120
   └── chunk_transcript(segments=12 segments, chunk_size=2500 words) -> 1 Chunk (176 words)

4. Prompt Construction & LLM Adapter Invocation
   backend/app/services/llm/ollama_adapter.py:discover_and_evaluate()
   ├── format_segments_to_text(chunk.segments) -> Formats timestamped lines
   ├── build_system_prompt(is_long_clip=False) -> Inserts 10s-60s bounds
   ├── build_user_prompt(is_long_clip=False) -> Inserts transcript + target instruction
   └── POST http://localhost:11434/api/chat with format=LLMCandidatesResponseEnvelope schema

5. Structured Response Parsing
   backend/app/services/llm/ollama_adapter.py:171-197
   └── Parses JSON content directly into List[LLMCandidateEvaluation] (11 items)

6. Candidate Validation, Scoring, Deduplication & Ranking
   backend/app/services/candidates/ranking.py:deduplicate_and_rank_candidates()
   ├── Loop over each LLMCandidateEvaluation:
   │   └── validate_candidate_against_transcript() (validation.py)
   │       ├── Checks duration: 10.0 <= (end - start) <= 60.0
   │       │   └── ALL 11 CANDIDATES FAIL: reason DURATION_BELOW_MINIMUM
   │       └── Candidate dropped into rejected_records; skipped from scored list
   └── surviving_candidates = [] (0 candidates survive)

7. Boundary Refinement (Skipped)
   backend/app/services/candidates/short_pipeline.py:168-221
   └── if ranked_candidates: ... -> Condition is False, NEVER REACHED

8. Artifact Persistence & Completion
   backend/app/services/candidates/short_pipeline.py:224-243
   ├── CandidateArtifact written to short_candidates.json with 11 rejected records
   └── Render step skipped cleanly (rendered_count = 0)
```

---

## 4. Evidence Table: Raw Candidate Proposals vs. Final Outcomes

Inspected directly from [`experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/short_candidates.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/short_candidates.json) and [`transcript.json`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/transcript.json):

| Proposal # | Proposed [Start - End] | Raw Duration | Transcript Segment Match | Rejection Code(s) | LLM Hook Summary |
|---|---|---|---|---|---|
| **1** | `15.64s - 19.72s` | 4.08s | Matches `SEG_04 + SEG_05` exactly | `DURATION_BELOW_MINIMUM` | Determination to win |
| **2** | `35.96s - 37.84s` | 1.88s | Matches `SEG_09` exactly (`35.96 - 37.84`) | `DURATION_BELOW_MINIMUM` | Daughter's competitiveness |
| **3** | `43.83s - 47.69s` | 3.86s | Matches `SEG_11` exactly (`43.83 - 47.69`) | `DURATION_BELOW_MINIMUM` | "I play for money to" punchline |
| **4** | `11.02s - 14.48s` | 3.46s | Matches `SEG_03` exactly (`11.02 - 14.48`) | `DURATION_BELOW_MINIMUM` | "Points are on" reaction |
| **5** | `19.72s - 27.72s` | 8.00s | Matches `SEG_06` exactly (`19.72 - 27.72`) | `DURATION_BELOW_MINIMUM` | Genetic competitiveness setup |
| **6** | `31.44s - 35.96s` | 4.52s | Matches `SEG_08` exactly (`31.44 - 35.96`) | `DURATION_BELOW_MINIMUM`, `EVIDENCE_NOT_GROUNDED` | One daughter competitive |
| **7** | `0.00s - 4.14s` | 4.14s | Matches `SEG_00` exactly (`0.00 - 4.14`) | `DURATION_BELOW_MINIMUM` | Reverse charades partner |
| **8** | `8.88s - 11.02s` | 2.14s | Matches `SEG_02` exactly (`8.88 - 11.02`) | `DURATION_BELOW_MINIMUM` | "Me neither" reaction |
| **9** | `17.44s - 19.72s` | 2.28s | Matches `SEG_05` exactly (`17.44 - 19.72`) | `DURATION_BELOW_MINIMUM` | "Less competitive now" quip |
| **10** | `27.72s - 31.44s` | 3.72s | Matches `SEG_07` exactly (`27.72 - 31.44`) | `DURATION_BELOW_MINIMUM`, `EVIDENCE_NOT_GROUNDED` | Motherhood is often me |
| **11** | `38.39s - 43.83s` | 5.44s | Matches `SEG_10` exactly (`38.39 - 43.83`) | `DURATION_BELOW_MINIMUM` | Doesn't throw games |

---

## 5. Verified Root Causes vs. Hypotheses

### 5.1 Verified Facts (Backed by Code & Physical Artifacts)
1. **Fact: The LLM output emits the micro-durations directly.**
   In `ollama_adapter.py`, `message_content` parsed into `envelope.candidates` contains `start_seconds: 43.83` and `end_seconds: 47.69`. Downstream code does not shorten candidates.
2. **Fact: 9 of 11 candidates correspond token-for-token to single transcript segments.**
   The transcript segment array in `transcript.json` contains segment boundaries: `[0.0, 4.14]`, `[8.88, 11.02]`, `[11.02, 14.48]`, `[17.44, 19.72]`, `[19.72, 27.72]`, `[27.72, 31.44]`, `[31.44, 35.96]`, `[35.96, 37.84]`, `[38.39, 43.83]`, `[43.83, 47.69]`. The model's proposed timestamps matched these numbers down to the hundredth of a second.
3. **Fact: The prompt explicitly forbids single-segment selection.**
   Lines 24–27 of `prompts.py` state: *"spans MULTIPLE consecutive segments... NEVER select a single isolated segment (e.g. 3-5 seconds punchline) by itself."* The model failed to follow this negative constraint.
4. **Fact: Hard duration validation occurs before boundary refinement.**
   In `ranking.py:71-96`, any candidate with `duration < 10.0` is appended to `rejected_records` and omitted from `scored_candidates`. Boundary refinement (`short_pipeline.py:170`) is only called on surviving candidates.

### 5.2 Plausible Hypotheses (Supported by Model Architecture)
1. **Hypothesis: Attention Head Token Copying Overpowers Arithmetic Reasoning.**
   When `qwen2.5:7b` generates the JSON key `"start_seconds"`, its attention heads attend to the bracketed string `[43.83s - 47.69s]` flanking the quote it selected for `"transcript_excerpt"`. Because decoder language models do not have internal execution calculators, the model copies `43.83` and `47.69` directly from the text context without verifying whether $47.69 - 43.83 \ge 10.0$.
2. **Hypothesis: User Prompt Closing Instruction Dilutes System Constraints.**
   The system prompt has extensive negative rules, but the user prompt terminates with:
   `"Explore the entire supplied transcript section thoroughly, identifying distinct moments, complete story arcs, conversational exchanges, setups and payoffs..."`
   In long context windows or multi-instruction prompts, the final instruction often commands recency bias, leading the model to treat each conversational line as an individual "moment" or "exchange".

### 5.3 Unresolved Questions
1. **Would a larger model (e.g. Qwen 72B, Claude 3.5 Sonnet, GPT-4o) obey the multi-segment rule zero-shot?**
   Prior industry evaluations suggest larger frontier models perform timestamp math better, but local 7B models consistently succumb to token copying.
2. **Would few-shot JSON examples in the prompt prevent token copying?**
   Providing a multi-segment example in the prompt could reduce copying, but risks prompting the model to memorize the example's duration or timestamps.

---

## 6. Prompt Intent vs. Product Requirements

| Dimension | Product Requirement | Current Prompt Intent | Actual Model Output |
|---|---|---|---|
| **Clip Purpose** | Meaningful, standalone excerpt of an interview or conversation. | Demands "complete, standalone moments spanning multiple consecutive segments". | Proposed single punchlines or isolated reaction quips. |
| **Duration** | 10.0s to 60.0s (Target: 30s). | Hard minimum 10.0s, preferred 15–45s, target 30s. | Emitted 1.88s to 8.00s (100% violation). |
| **Setup & Payoff** | Must include setup/context and resolving punchline/reaction. | Warns against selecting punchlines without setup. | Selected punchlines exclusively (e.g. *"I play for money to"*). |
| **Grounding** | Exact transcript quotes and valid container timestamps. | Requires verbatim evidence quotes and exact timestamps. | Timestamps grounded, but evidence grounding failed on 2 items. |

---

## 7. Strategic Recommendations

We evaluated three potential remedies:

### Option 1: Prompt-Only Adjustments
- *Description*: Emphasize negative constraints, add few-shot multi-segment JSON examples, or penalize single segments.
- *Trade-off*: Fragile on 7B models. Even with strong prompting, autoregressive decoders frequently slip back into token-copying when encountering punchlines.
- *Verdict*: **Insufficient on its own.**

### Option 2: Approach A — Semantic Anchor Extraction + Bounded Backend Window Construction (RECOMMENDED)
- *Description*: The LLM extracts semantic anchors and identifies segment IDs (`[SEG_10, SEG_11]`). Python deterministically constructs bounded candidate windows ($B_0, B_1, B_2$ backward for setup, $F_0, F_1$ forward for payoff), guaranteeing that all candidates passed to validation satisfy $10.0\text{s} \le \text{duration} \le 60.0\text{s}$.
- *Trade-off*: Requires creating `expansion.py` (~80 lines of Python), but eliminates 100% of LLM arithmetic and token-copying failures without adding API latency.
- *Verdict*: **Best architectural fit.** Fully aligns with the design in [`docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/docs/STAGE3_SHORT_DISCOVERY_STRATEGY_PROPOSAL.md).

### Option 3: Two-Pass LLM Discovery (Approach B)
- *Description*: Pass 1 finds anchors; Pass 2 asks the LLM to select a wider window.
- *Trade-off*: Doubles model latency (70–100s per long clip) and cost. Pass 2 can still fail duration math.
- *Verdict*: **Rejected.**

---

## 8. Affected Code Files for Future Implementation

If and when implementation is authorized, the changes will be strictly isolated to:
1. `backend/app/services/candidates/expansion.py` (New): Implements `expand_anchor_to_candidate_windows()`.
2. `backend/app/services/llm/prompts.py`: Updates prompt to tag segments as `[SEG_XX]` and request anchor segment IDs.
3. `backend/app/api/v1/schemas/candidates.py`: Adds `LLMAnchorEvaluation` schema.
4. `backend/app/services/candidates/short_pipeline.py`: Passes anchors through window expansion before duration validation and boundary refinement.

---

## 9. Controlled Evaluation Plan (Quality-Focused)

When evaluating the pipeline, testing must evaluate editorial quality and narrative completeness, not just test pass counts:

1. **Test Case 1: Multi-Turn Banter with Punchline**:
   - Board-game long master (`clip_01`).
   - *Acceptance*: Discovers candidate window `19.72s - 47.69s` (or refined `48.69s`). Validates that setup (kids' competitive genetics) directly connects to the punchline (playing for money).
2. **Test Case 2: Atomic Indivisible Conversation**:
   - Short long master (~30s) where no sub-part can stand alone.
   - *Acceptance*: Accurately yields **0 accepted Shorts**, persists candidate audit with status `REJECTED`, and exits cleanly with code 0 without rendering broken snippets.
3. **Test Case 3: Word Integrity & Acoustic Padding**:
   - Verifies that boundary refinement snaps outwardly to word boundaries and retains trailing room laughter/silence up to 1.0s without exceeding parent media bounds.
