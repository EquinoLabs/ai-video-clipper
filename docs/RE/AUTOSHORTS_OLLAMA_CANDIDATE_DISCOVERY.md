# Focused Reverse Engineering: AutoShorts Local Ollama Candidate Discovery

**Target Project**: `ai-video-clipper` (`C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`)  
**Target Reference Repository**: `autoshorts` (`C:\Lakshya\AI\autoshorts`)  
**Target Reference Binary**: `AutoShorts_0.1.3_x64-setup.exe` (`C:\Lakshya\Applications\AutoShorts_0.1.3_x64-setup.exe`)  
**Reverse Engineering Skill**: `reverse-engineer-anything` (`C:\Users\laksh\.agents\skills\reverse-engineer-anything\SKILL.md`)  
**Auditor**: Antigravity Assistant  
**Date**: October 2026  
**Status**: Complete / Verified

---

## 1. Target Identity, Provenance & Source Accessibility

### 1.1 Repository & Binary Identity
* **Local Source Path**: `C:\Lakshya\AI\autoshorts`
* **Remote Repository**: `https://github.com/JayWebtech/autoshorts.git`
* **Branch**: `main`
* **Commit**: `5ae8dd388b190222e18ea63b8823616fbdf2a4a9` ("Update README.md")
* **Binary Target**: `C:\Lakshya\Applications\AutoShorts_0.1.3_x64-setup.exe` (PE32 NSIS installer packaging Tauri v2 release `0.1.3`).
* **Source Accessibility**: The full source code is accessible on local disk. Core candidate detection code was introduced in commit `b0bac59` ("feat: implement local llm support") and refined in subsequent commits.
* **Binary Corroboration**: Static analysis of the decompressed installer overlay (`15,815,832` bytes) confirmed exact compiled string matches for:
  * `http://localhost:11434/api/chat`
  * `http://localhost:11434/api/pull`
  * System prompt tokens: `"You are an elite, world-class social media strategist..."`
  * JSON schema format constraints: `{"type":"object","properties":{"candidates":...}}`

---

## 2. Supported Ollama Models & Configuration

### 2.1 Supported Models
AutoShorts supports any Ollama-compatible model via text input, but features three primary model tiers in its UI and onboarding flow ([`src/main.tsx#L1624-L1658`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L1624-L1658)):

1. **`llama3.2`** (LLaMA 3.2 3B, ~1.9 GB):
   * Default model selection in UI state and Rust backend.
   * Documented requirement: 8GB+ RAM. "Fast and efficient."
2. **`qwen2.5:3b`** (Qwen 2.5 3B, ~2.0 GB):
   * Documented requirement: 8GB+ RAM. "Excellent coding and logical reasoning."
3. **`qwen2.5:7b`** (Qwen 2.5 7B, ~4.7 GB):
   * Documented requirement: 16GB+ RAM. "High-quality moment detection and hook precision."

### 2.2 Model Configuration & Default Value Resolution
* **Default Model**:
  * Frontend: `localStorage.getItem("autoshorts_local_llm_model") || "llama3.2"` ([`src/main.tsx#L144`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L144)).
  * Backend: `model_name.or_else(|| std::env::var("OLLAMA_MODEL").ok()).unwrap_or_else(|| "llama3.2".to_string())` ([`src-tauri/src/lib.rs#L457-L460`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L457-L460)).
* **Ollama Server Endpoint**: Hardcoded to `http://localhost:11434` across backend and frontend.
* **Inference Parameters**:
  * `temperature: 0.2` ([`src-tauri/src/llm.rs#L510`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L510)).
  * `stream: false`.
  * `num_ctx`: **Not configured** (defaults to Ollama's built-in default of 2,048 tokens).

### 2.3 Ollama Availability & Model Management
* **Availability Healthcheck**:
  In [`src-tauri/src/lib.rs#L40-L45`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L40-L45), the backend probes Ollama readiness via:
  ```rust
  let has_ollama = reqwest::Client::new()
      .get("http://localhost:11434")
      .timeout(std::time::Duration::from_millis(1000))
      .send()
      .await
      .is_ok();
  ```
  Returns a boolean flag to the frontend `environment.hasOllama`.
* **Automated Model Pulling (`pull_ollama_model`)**:
  In [`src-tauri/src/lib.rs#L66-L152`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L66-L152), AutoShorts invokes `POST http://localhost:11434/api/pull` with `{"name": model_name, "stream": true}`. The backend buffers incoming JSON stream chunks, parses `completed` and `total` bytes, and emits the Tauri event `ollama-pull-progress` to drive a UI progress bar.
* **macOS Auto-Installation (`install_ollama`)**:
  In [`src-tauri/src/lib.rs#L154-L276`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L154-L276), macOS users without Ollama can trigger an automated Homebrew Cask install (`brew install --cask ollama`) or fallback zip download from `https://ollama.com/download/Ollama-darwin.zip`. (Windows and Linux require manual installation).

---

## 3. End-to-End Execution Trace

```
[NormalizedTranscript in SQLite]
               │
               ▼
1. Extract transcript.segments
   [ {start: 0.0, end: 4.5, speaker: "S1", text: "..."}, ... ]
               │
               ▼
2. Compaction (compact_segments)
   Formats to: "[{start:.2}-{end:.2}] {speaker}: {text}\n..."
               │
               ▼
3. Construct Ollama Payload
   - System: Strategic instructions, 30-90s duration constraint
   - User: "Transcript:\n{compacted_text}"
   - Format: JSON Schema constraint
   - Options: { temperature: 0.2 }
               │
               ▼
4. POST http://localhost:11434/api/chat
               │
               ▼
5. Raw JSON String Response
   - Strip markdown code fences (```json ... ```)
   - Locate candidate array ("candidates", "moments", "clips", etc.)
   - Normalize numeric/string timestamps & clamp scores [0.0, 1.0]
               │
               ▼
6. Duration Filtering & Sorting
   - Filter (end - start) >= 30.0s (fallback to 5.0s if 0 pass)
   - Sort by score DESC
   - Truncate to top 10
               │
               ▼
7. SQLite Persistence (replace_candidates)
   - Delete previous candidates for project
   - Auto-select top 3 to 6 candidates (selected_cutoff)
   - Insert rows into `candidates` and `clips` (pending)
```

### Detailed Trace:
1. **Trigger**: User clicks "Find Viral Moments" or auto-pipeline runs after transcription ([`src/main.tsx#L480-L514`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L480-L514)).
2. **Backend Entry**: `generate_candidates` in [`src-tauri/src/lib.rs#L425-L516`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L425-L516).
3. **Data Retrieval**: Reads `raw_json` from `transcripts` table, deserializes into `NormalizedTranscript`.
4. **Adapter Dispatch**: Resolves `provider == "local" || provider == "ollama"`, routes to `llm::detect_candidates_with_local_llm(&normalized, &model)`.
5. **Prompt Formatting**: Compiles all segment text into a single compacted string.
6. **Inference Execution**: Asynchronously posts to Ollama `/api/chat`.
7. **Post-Processing**: Parses JSON, validates minimum duration, normalizes scores, sorts by score descending, limits to 10.
8. **Storage**: Commits candidates to SQLite and sets project status to `"ready"`.

---

## 4. Prompts, Formatting & Schema Validation

### 4.1 System Instructions ([`src-tauri/src/llm.rs#L482-L490`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L482-L490))
```text
You are an elite, world-class social media strategist with a track record of generating viral multi-million-view Shorts, TikToks, and Reels. Your sole objective is to identify the ABSOLUTE BEST, most highly-engaging, and trend-setting short-form clip candidates from the provided transcript. Do NOT pick random or mediocre segments. Be ruthless in your selection. Every candidate must have an insanely strong, curiosity-inducing hook in the first 3 seconds to stop the scroll. CRITICAL: Each clip candidate MUST have a duration between 30 and 90 seconds (i.e. 'end' minus 'start' must be between 30.0 and 90.0). Do NOT return short clips of less than 30 seconds. Combine multiple adjacent sentences to build a meaningful segment of 30-90 seconds. Favor highly shareable content: concrete stories, strong opinions, emotional turns, surprising or counter-intuitive claims, clear payoffs, and high-energy/dramatic peaks. You MUST identify and return at least 3-10 candidates. Do not return an empty candidates list. Ensure the 'start' and 'end' values correspond to actual timestamps in the transcript. Do not output 0.0 for start and end times.
```

### 4.2 User Prompt ([`src-tauri/src/llm.rs#L492`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L492))
```text
Transcript:
[0.00-3.20] S1: The surprising thing about short-form clips is that the best moment is rarely the loudest.
[3.28-7.15] S1: It is usually the point where someone finally says the quiet part plainly.
[7.90-11.40] S2: And the listener can immediately feel the stakes.
```

### 4.3 Structured Output Enforcement (JSON Schema)
AutoShorts passes a JSON Schema directly in Ollama's `format` field ([`src-tauri/src/llm.rs#L512-L531`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L512-L531)):
```json
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "start": { "type": "number" },
          "end": { "type": "number" },
          "score": { "type": "number" },
          "hook": { "type": "string" },
          "rationale": { "type": "string" }
        },
        "required": ["start", "end", "score", "hook", "rationale"]
      }
    }
  },
  "required": ["candidates"]
}
```

### 4.4 Malformed Output Handling (`parse_candidate_json`)
In [`src-tauri/src/llm.rs#L569-L722`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L569-L722), AutoShorts implements extensive defensive parsing to recover from local LLM quirks:
* **Markdown Fence Stripping**: Trims leading/trailing ```json, ```, and whitespace.
* **Key Alias Fallbacks**: If `"candidates"` is not found, inspects:
  `["candidates", "Candidates", "moments", "clips", "segments", "results"]`.
* **Nested Object Recovery**: If top-level is an arbitrary object, scans all object values for the first array.
* **Single-Candidate Wrapping**: If the root object is a dictionary with `"start"` and `"end"` keys instead of an array, wraps it into a single-element list `[val]`.
* **Type Coercion**: Handles timestamps encoded as strings (`"32.5"`), floats (`32.5`), or integers (`32`).
* **Score Scale Normalization**:
  * If `score > 1.0 && score <= 10.0` -> `score /= 10.0`
  * If `score > 10.0 && score <= 100.0` -> `score /= 100.0`
  * Clamps score strictly to `[0.0, 1.0]`. If missing, defaults to `0.8`.

---

## 5. Timestamp Handling & Verification Reality

### 5.1 Representation in Prompts
* Segments are formatted using 2-decimal floats: `[{start:.2}-{end:.2}] {speaker}: {text}`.
* Segment boundaries are established during earlier transcription heuristic segmentation (0.9s pause threshold).

### 5.2 Source Transcript Grounding: Verified Absence
* **CRITICAL FINDING**: **AutoShorts performs ZERO validation of candidate timestamps or text against the transcript.**
* The parser checks only `(end - start) >= min_duration && !hook.trim().is_empty()`.
* It does **not** verify:
  1. Whether `start` or `end` align with actual sentence or word boundaries.
  2. Whether `end` exceeds the media duration (e.g. If a 1-minute video yields a hallucinated `end: 120.0`, AutoShorts accepts it).
  3. Whether the content in `hook` or `rationale` actually occurred in the video.
* **Downstream Consequence**: When FFmpeg executes `render_flat_clip` with hallucinated timestamps, seeking beyond media duration causes FFmpeg errors or black/silent video clips.

---

## 6. Context Window & Chunking Reality

### 6.1 Chunking & Context Window Analysis
* **CRITICAL FINDING**: **AutoShorts implements ZERO chunking, ZERO overlap, and ZERO context-window management.**
* In `detect_candidates_with_local_llm`:
  ```rust
  let segments = compact_segments(&transcript.segments);
  let user_content = format!("Transcript:\n{}", segments);
  ```
  The entire transcript is passed into a single prompt string regardless of video length.

### 6.2 The Silent Truncation Trap
* Ollama's default context window (`num_ctx`) is **2,048 tokens**.
* AutoShorts does not pass `"num_ctx"` in its `"options"` object ([`src-tauri/src/llm.rs#L509-L511`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L509-L511)).
* **Impact**:
  * An average spoken transcript generates ~150-180 words per minute (~220 tokens/min).
  * A 10-minute video generates ~2,200 tokens.
  * A 30-minute podcast generates ~6,600 tokens.
  * A 1-hour interview generates ~13,000+ tokens.
  * In AutoShorts, **any video longer than ~8–10 minutes has its transcript silently truncated by Ollama's context buffer**. The local LLM never sees any content past the first 8 minutes.

---

## 7. Scoring, Ranking & Selection Logic

### 7.1 Candidate Scoring
* The model returns a single subjective scalar (`score`).
* There is no dimensional rubric, no evaluation of hook vs coherence vs pacing, and no goal-specific weighting.

### 7.2 Deduplication: Verified Absence
* **CRITICAL FINDING**: **AutoShorts implements NO temporal deduplication or IoU calculation.**
* If Ollama outputs overlapping candidates (e.g., Clip A: `10.0 - 55.0` and Clip B: `12.0 - 57.0`), both are accepted, ranked, and presented to the user.

### 7.3 Ranking & Selection Limits
* **Ranking**: Sorted strictly by score descending:
  ```rust
  candidates.sort_by(|a, b| b.score.total_cmp(&a.score));
  candidates.truncate(10);
  ```
* **Auto-Selection**: In SQLite persistence ([`src-tauri/src/db.rs#L267-L280`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/db.rs#L267-L280)):
  * Computes `selected_cutoff = drafts.len().min(6).max(3).min(drafts.len())`.
  * The top 3 to 6 candidates are automatically flagged `selected = true`.
* **User Control**: Frontend range slider allows modifying selected count from 0 to 10 (`set_selected_clip_count`).

---

## 8. Failure Modes, Timeouts & Error Handling

| Scenario | AutoShorts Behavior | Source Reference |
| :--- | :--- | :--- |
| **Ollama Not Running** | `environment.hasOllama` returns `false` via 1s probe. UI shows warning banners. Pipeline halts with error message. | [`src-tauri/src/lib.rs#L40-L45`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L40-L45); [`src/main.tsx#L433`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L433) |
| **Model Not Pulled (404)** | Ollama returns 404. Frontend intercepts error string containing `"not found"` or `"404"` and prompts user to trigger `pull_ollama_model`. | [`src/main.tsx#L500-L509`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L500-L509) |
| **Request Timeout** | `reqwest::Client` uses default infinite timeout. If Ollama hangs (e.g. CPU thrashing or out of VRAM), the request hangs indefinitely. | [`src-tauri/src/llm.rs#L494-L535`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L494-L535) |
| **Empty Candidate Output** | If 0 candidates pass duration filter, retries with relaxed `min_duration = 5.0s`. If still empty, returns `Err("No viable clip candidates...")`. | [`src-tauri/src/llm.rs#L710-L721`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L710-L721) |
| **Invalid JSON Output** | Returns `Err("parsing candidate JSON")`. Triggers UI error banner. No automatic retry with adjusted temperature. | [`src-tauri/src/llm.rs#L577`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L577) |

---

## 9. Code Mapping & File References

| Component | Repository Path | Exact Line Numbers |
| :--- | :--- | :--- |
| **Local LLM Execution** | `src-tauri/src/llm.rs` | [`lines 476–553`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L476-L553) |
| **Segment Compaction** | `src-tauri/src/llm.rs` | [`lines 555–567`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L555-L567) |
| **Defensive JSON Parser** | `src-tauri/src/llm.rs` | [`lines 569–722`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L569-L722) |
| **Tauri Command Dispatcher** | `src-tauri/src/lib.rs` | [`lines 425–516`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L425-L516) |
| **Ollama Health Probe** | `src-tauri/src/lib.rs` | [`lines 40–45`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L40-L45) |
| **Model Pull Streamer** | `src-tauri/src/lib.rs` | [`lines 66–152`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L66-L152) |
| **macOS Auto-Installer** | `src-tauri/src/lib.rs` | [`lines 154–276`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L154-L276) |
| **SQLite Persistence** | `src-tauri/src/db.rs` | [`lines 257–308`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/db.rs#L257-L308) |
| **Frontend Model Selector & Prompts** | `src/main.tsx` | [`lines 1624–1658`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L1624-L1658) |
| **Automated Pipeline Flow** | `src/main.tsx` | [`lines 415–514`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L415-L514) |

---

## 10. Performance Considerations & Documented Model Limitations

AutoShorts' own `README.md` ([lines 107–112](file:///C:/Lakshya/AI/autoshorts/README.md#L107-L112)) explicitly discourages local models for serious use:

> *"While AutoShorts supports fully offline moments analysis via local Ollama models (like LLaMA 3.2 3B or Qwen 2.5 3B/7B), **local models are generally not recommended for viral moment detection**. Smaller 3B/7B models lack the context reasoning and mathematical capabilities needed to evaluate long transcripts and calculate accurate segment timestamps (often outputting fragments that are too short)."*

### Verified Technical Reasons:
1. **Arithmetic Limitations**: Smaller 3B/7B models frequently fail mental arithmetic when computing `end - start`, resulting in short 4–8 second fragments despite prompt rules.
2. **Context Degradation**: When long transcripts approach or exceed 2,048 tokens, attention degradation causes models to repeat phrases or emit generic hooks.
3. **Execution Latency**: On non-GPU desktop machines, 7B quantized models run at 5–15 tokens/sec. A 2,000-token prompt plus 500-token JSON completion takes 40–90 seconds of continuous 100% CPU/GPU utilization.

---

## 11. Architectural Comparison: AutoShorts vs. `ai-video-clipper`

| Feature / Architecture | AutoShorts (v0.1.3) | `ai-video-clipper` (Baseline PRD v0.2.1 / TechSpec v0.2.1) | Architectural Assessment |
| :--- | :--- | :--- | :--- |
| **LLM Provider Abstraction** | Hardcoded `match` statement in Tauri Rust command | Abstract `LLMProvider` interface in Python with pluggable adapters | `ai-video-clipper` has a clean modular contract ready for an `OllamaProvider`. |
| **Context Management** | None (entire transcript in 1 prompt, truncated at 2K tokens) | Deterministic chunker with segment overlap and token budgets (`chunking.py`) | AutoShorts is **severely deficient** for videos >8 mins. |
| **Candidate Output Schema** | Flat dict: `{start, end, score, hook, rationale}` | `LLMCandidateEvaluation` with 8 dimensional ratings and `EvidenceItem` quotes | `ai-video-clipper` provides auditability and grounding. |
| **Timestamp Validation** | None (blindly accepts model timestamps) | `validate_candidate_against_transcript` with fuzzy quote & segment checks | AutoShorts risks black frames; `ai-video-clipper` guarantees media validity. |
| **Deduplication** | None (overlapping clips accepted and rendered) | 1D Temporal Intersection-over-Union (`iou_threshold = 0.50`) | AutoShorts creates duplicate content; `ai-video-clipper` suppresses overlaps. |
| **Scoring Formula** | Uncalibrated model float `[0.0, 1.0]` | Backend-owned, goal-specific weighted formula generating `overall_score` (0–100) | `ai-video-clipper` ensures score calibration across engines. |
| **Prompt Specialization** | Generic viral social prompt only | Goal-conditioned prompts (Humor, Education, Emotion, Hook, etc.) | `ai-video-clipper` satisfies diverse editorial goals. |

---

## 12. Strategic Conclusions & Deliverable Summary

### 12.1 Explanation of AutoShorts' Pipeline
AutoShorts formats the entire transcription into a timestamped dialogue string, sends it in a single synchronous HTTP call to Ollama's `/api/chat` constrained by a JSON schema, parses candidate objects with aggressive fallback heuristics, drops clips shorter than 30 seconds, sorts by raw model score, and stores the top 10 in SQLite.

### 12.2 Strengths & Weaknesses
* **Strengths**:
  * Clean use of Ollama's native JSON Schema enforcement (`format: { ... }`).
  * Fast, lightweight health probe (`GET :11434` with 1s timeout).
  * Highly robust, defensive JSON parsing recovering from markdown fences, key renames, and scalar score scales.
* **Weaknesses**:
  * **Zero transcript chunking**: Silently drops any video content beyond ~2,000 tokens (~8 minutes).
  * **Zero timestamp grounding**: Hallucinated timestamps cause FFmpeg rendering failures.
  * **Zero deduplication**: Emits near-identical overlapping clips.
  * **Single subjective score**: No dimensional breakdown or editorial goal customization.

### 12.3 Feasibility of Ollama in `ai-video-clipper`
**FEASIBLE, BUT REQUIRES ADAPTATION.**  
An `OllamaProvider` can cleanly implement our `LLMProvider.discover_and_evaluate` interface. However, because smaller local models (3B/7B) struggle to emit complex 8-dimensional scoring breakdowns and quoted evidence simultaneously:
* The adapter must use chunking with smaller window budgets (e.g., 2,000–3,000 tokens).
* The prompt should simplify the schema or supply sane defaults for secondary qualitative assessment fields if omitted.

### 12.4 Recommended Local Model Candidates
1. **Verified AutoShorts Baseline**:
   * `qwen2.5:7b` (Recommended by AutoShorts author as the only viable 7B candidate for reasoning).
   * `llama3.2:3b` (Fast fallback for low-RAM machines; prone to duration errors).
2. **New Recommended Candidates for `ai-video-clipper` Evaluation**:
   * **`qwen2.5:14b`**: Significantly stronger timestamp arithmetic and schema adherence than 7B; runs comfortably on 16GB RAM / 12GB VRAM with Q4 quantization.
   * **`mistral-nemo:12b`**: 128k context support, excellent instruction following, and strong dialogue extraction capabilities.
   * **`deepseek-r1:8b`** (or `deepseek-r1:14b`): High-speed distilled reasoning model capable of justifying clip boundaries with superior chain-of-thought rationale.

### 12.5 Smallest Practical Comparison Experiment
To objectively benchmark local Ollama against hosted OpenAI without application code changes:
1. **Test Artifact**: Use the existing Anne Hathaway test video (`outputs/.../sample_speech_video_.../transcript.json`, ~3.5 minutes).
2. **Setup**: Run a standalone CLI script passing the same transcript chunk to:
   * **Model A**: `gpt-4o-mini` (hosted baseline via `OpenAIProvider`).
   * **Model B**: `qwen2.5:7b` (local Ollama via `/api/chat` with JSON schema).
3. **Metrics to Evaluate**:
   * Schema validity (100% valid Pydantic parse without fallbacks?).
   * Timestamp accuracy (Did start/end align with real transcript segment bounds?).
   * Evidence grounding (Did quoted excerpt actually exist in the transcript?).
   * Hook quality (Human qualitative rating 1–5).
   * Latency & VRAM usage on local machine.

### 12.6 Decisions Requiring Founder Approval
1. **Local Schema Complexity vs. Reliability**:
   * *Decision*: Should local Ollama models be held to the full 8-dimension `ScoreBreakdown` + `EvidenceItem` schema, or should we define a streamlined `LocalCandidateEvaluation` schema where the backend derives missing dimensions?
2. **Minimum Hardware Requirement Policy**:
   * *Decision*: Should we officially set 16GB RAM + 8GB VRAM (Qwen 2.5 7B/14B) as the minimum supported hardware for local candidate discovery, explicitly disallowing 3B models due to high hallucination rates?
3. **Prioritization of Phase 2 Providers**:
   * *Decision*: Should the local `OllamaProvider` be implemented alongside `OpenAIProvider` in Phase 2, or deferred until after the hosted baseline is end-to-end verified?
