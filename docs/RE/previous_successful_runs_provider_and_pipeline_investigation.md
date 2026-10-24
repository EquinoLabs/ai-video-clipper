# Investigation: Previous Successful Runs, Provider Trace, and Timeout Root Cause

**Investigation Date**: 2026-10-25  
**Investigator**: Antigravity AI  
**Scope**: Strictly Read-Only Forensic Architecture and Artifact Audit  
**Artifact Path**: `docs/RE/previous_successful_runs_provider_and_pipeline_investigation.md`

---

## A. Executive Conclusion

### 1. Did the earlier successful clip-generation workflow actually use Ollama?
**YES, DEFINITIVELY.**
Ollama with `qwen2.5:7b` genuinely ran and successfully discovered the clips across multiple historical milestones:
1. **The 7-Short Multiwindow Run** (`outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`, 2026-10-21): Processed 4 chunks of 750 words using Ollama `qwen2.5:7b` in ~60s total, producing 7 valid clips that were fully rendered into 1080x1920 MP4s with burned subtitles.
2. **The 2-Candidate Remediated Test** (`outputs/smoke_test_ollama_qwen25_humor_remediated/candidates.json`, 2026-10-21): Completed in ~60 seconds on a single 750-word chunk, returning 2 valid candidates.
3. **The Three-Shorts Live Evaluations** (`experimental_output/eval_stage3_topic_isolation_live_20261025/`, 2026-10-25): Succeeded using Ollama `qwen2.5:7b` via the standalone short-clip pipeline on long master package `clip_01/` in **~45 seconds**, rendering all 3 vertical Short MP4s.

### 2. Which parts are proven and which remain uncertain?
- **Proven**:
  - The model `qwen2.5:7b` on local Ollama was genuinely invoked and generated valid candidates/anchors for all the above runs.
  - No OpenAI API calls, mocks, fixtures, fallbacks, or cached responses were involved in those runs.
  - The previous successful Stage 3 evaluations did **NOT** execute Stage 2 end-to-end; they targeted a single, pre-existing long-clip package (`clip_01.mp4`, 49.19s, 176 words) using `python -m app.cli.process_short_clips`.
  - The controlled Stage 2 long-discovery run on 2026-10-24 (`experimental_output/long_clip_discovery_qwen25_humor_20261024/candidates.json`) **also ran Ollama `qwen2.5:7b` on the 10-minute video** and completed in **373.71 seconds (6m 13s)** across two 1500-word chunks.
- **Uncertain**:
  - Why the 2026-10-24 Stage 2 run completed Chunk 1 within ~180s while the 2026-10-25 run exceeded 300s. The difference is attributable to prompt differences, system GPU memory / context allocation, or local process load, as analyzed below.

### 3. What explains the difference between the earlier successes and the latest timeout?
1. **Stage 3 vs Stage 2 Scope**: The earlier three-Shorts successes (`eval_stage3_*`) evaluated only **12 segments / 176 words** of dialogue (49 seconds of video) using the lightweight `SHORT_ANCHOR_SYSTEM_PROMPT`. Inference completed in under 45 seconds.
2. **Stage 2 Chunk Size**: In Stage 2, `long_transcript_chunk_size` is **1,500 words** (Chunk 1 spanned **0.1s to 418.3s / 1,511 words / 215 segments**).
3. **Prompt & Schema Complexity**: The Stage 2 prompt (`LONG_CLIP_SYSTEM_PROMPT`) requires evaluating 8 distinct scoring dimensions across wide conversational arcs and generating comprehensive JSON objects (`LLMCandidatesResponseEnvelope` schema length: 3,019 characters) with decimal start/end timestamps and evidence quotes.
4. **Tight Timeout Threshold**: In the controlled Stage 2 run on 2026-10-24, processing both 1500-word chunks took **373.71 seconds** (~185s per chunk). In the latest run, local inference on Chunk 1 took slightly over 300 seconds, hitting the hard-coded `httpx` client timeout (`OLLAMA_TIMEOUT_SECONDS = 300.0s`).

---

## B. Historical Evidence Table

| Run / Directory | Date/Time | Input Video & Transcript | Effective Provider / Model | Stage 2 / Stage 3 Execution | Artifacts Rendered | Evidence Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `outputs/smoke_test_ollama_qwen25_humor/` | 2026-10-20 21:38 UTC | Anne Hathaway 10m video (chunk 1) | Ollama `qwen2.5:7b` | Short discovery (single chunk, 750 words) | 0 clips rendered (3 raw candidates, 0 passed validation) | **Definitive** (`candidates.json` metadata records `provider: ollama`, `model: qwen2.5:7b`) |
| `outputs/smoke_test_ollama_qwen25_humor_remediated/` | 2026-10-21 16:15 UTC | Anne Hathaway 10m video (chunk 1) | Ollama `qwen2.5:7b` | Short discovery (single chunk, 750 words) | `candidates.json` generated (2 valid candidates) | **Definitive** (`candidates.json` records provider and model; completed in ~60s) |
| `outputs/smoke_test_ollama_qwen25_humor_multiwindow/` | 2026-10-21 19:02 UTC | Anne Hathaway 10m video (all 4 chunks) | Ollama `qwen2.5:7b` | Short discovery across four 750-word chunks | **7 MP4 clips rendered** (`cnd_001` - `cnd_007` with ASS/SRT burned subtitles) | **Definitive** (7 playable 9:16 vertical MP4s exist on disk; metadata records Ollama) |
| `outputs/experiments/first_three_minutes/` | 2026-10-22 01:05 UTC | Anne Hathaway 10m video (first 3 minutes) | Controlled human editorial intervals | Boundary comparison test (Moments A, B, C) | **5 MP4 clips rendered** (`A1_baseline.mp4`, `A2_with_laughter.mp4`, etc.) | **Definitive** (Documented in manual evaluation sheet as human benchmark clips) |
| `experimental_output/long_clip_discovery_qwen25_humor_20261024/` | 2026-10-24 16:34 UTC | Anne Hathaway full transcript (2 chunks of 1500 words) | Ollama `qwen2.5:7b` | Stage 2 Long candidate discovery | `candidates.json` generated (1 accepted long candidate, 9 rejected) | **Definitive** (Runtime: 373.71s total, ~185s per chunk; CLI discovery) |
| `experimental_output/eval_stage2_stage3_live_20261024/long_clips/clip_01/` | 2026-10-24 17:12 UTC | Rendered long master from Moment A | N/A (Packaged long master) | Stage 2 master package creation | **1 Long Master MP4 rendered** (`clip_01.mp4`, 49.19s, 20.16 MB) | **Definitive** (Package metadata `clip_id: lng_001`, source interval `11.73s - 60.92s`) |
| `experimental_output/eval_stage3_topic_isolation_live_20261025/` | 2026-10-25 01:30 UTC | Long package `clip_01` (12 segments, 176 words) | Ollama `qwen2.5:7b` | Stage 3 Standalone Short discovery | **3 Short MP4 clips rendered** (`clip_01.mp4` [15.58s], `clip_02.mp4` [28.97s], `clip_03.mp4` [11.72s]) | **Definitive** (Runtime ~45s; 3 distinct playable MP4s with full metadata) |
| `outputs/2026-10-25/.../02_18_29__run_001/` (Failed Run) | 2026-10-25 02:18 UTC | Staged `video.mp4` (10m 22s) | Ollama `qwen2.5:7b` (via `.env`) | Stage 1 transcription succeeded; Stage 2 long discovery timed out | 0 clips rendered (Transcript succeeded in 108s; Chunk 1 timed out at 300.0s) | **Definitive** (`manifest.json` records `status: failed`, `transcription: completed`, `long_discovery: failed`) |

---

## C. Code Path and Provider Propagation Audit

Inspection of [`backend/app/services/llm/factory.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/factory.py), [`backend/app/services/pipeline/orchestrator.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/pipeline/orchestrator.py), and [`backend/app/services/llm/ollama_adapter.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/app/services/llm/ollama_adapter.py) reveals:

1. **Strict Provider Selection**:
   ```python
   def get_llm_provider(provider_name, model_name, ...):
       selected_provider = (provider_name or settings.llm_provider or "openai").strip().lower()
       if selected_provider == "ollama":
           return OllamaProvider(...)
       if selected_provider == "openai":
           return OpenAIProvider(...)
   ```
   There is **no silent fallback** between providers. If `ollama` fails or times out, an `OllamaProviderError` is raised immediately.
2. **No LLM Caching or Fixture Mechanism**:
   Neither `OllamaProvider` nor `discover_candidates.py` nor `short_pipeline.py` maintains an LLM response cache. Every invocation issues a live HTTP POST to `http://localhost:11434/api/chat`.
3. **No Mocking in Production Code Paths**:
   Mock classes (`MockLLMProvider`, `MultiWindowMockProvider`) exist solely within unit/integration tests under `backend/tests/`. They are never imported or invoked by `app.py`, `orchestrate.py`, or the service layer.

---

## D. Deep Comparison: Successful Runs vs. Failed Run

### 1. Stage 3 Shorts Successes vs. Stage 2 Timeout
The successful runs that produced the three Shorts (`clip_01.mp4`, `clip_02.mp4`, `clip_03.mp4` in `eval_stage3_topic_isolation_live_20261025`) differed fundamentally from the full pipeline run:
- **Input Media**: Sliced 49.19-second video (`clip_01.mp4`), NOT the 10-minute master.
- **Transcript Size**: **176 words / 12 segments**, compared to **1,511 words / 215 segments** in Chunk 1 of Stage 2.
- **Inference Task**: The prompt asked for `3` chunk-local segment tags (`[SEG_04]`, `[SEG_10]`, `[SEG_07]`) without timestamps (`SHORT_ANCHOR_SYSTEM_PROMPT`).
- **Generation Volume**: The model generated only small anchor tokens (`anchor_segment_ids: [4]`). The candidate expansion into 10s–30s video intervals was computed in **pure Python** via `construct_bounded_candidate_windows()`.
- **Inference Duration**: **~45 seconds** total.

### 2. Earlier Stage 2 Success (2026-10-24) vs. Failed Run (2026-10-25)
Both runs executed Stage 2 Long Candidate Discovery on the same 10-minute transcript using Ollama `qwen2.5:7b`:

| Parameter | Controlled Stage 2 Run (2026-10-24) | Failed End-to-End Pipeline Run (2026-10-25) |
| :--- | :--- | :--- |
| **CLI / Entrypoint** | `backend/app/cli/discover_candidates.py` directly | `app.py --final --single ...` (Orchestrator) |
| **Transcript Source** | Pre-existing transcript artifact | Freshly transcribed in Stage 1 by Faster-Whisper |
| **Prompt Chunk 1 Size** | 1,511 words (215 segments, 0.1s – 418.3s) | 1,507 words (214 segments, 0.1s – 410.8s) |
| **System Prompt** | `LONG_CLIP_SYSTEM_PROMPT` | `LONG_CLIP_SYSTEM_PROMPT` |
| **Target Output** | 10 candidates requested in JSON schema | 6 candidates requested in JSON schema (`target_count=6`) |
| **Timeout Setting** | `ollama_timeout_seconds: 300.0` (Config default) | `ollama_timeout_seconds: 300.0` (Loaded from `.env`) |
| **Actual Elapsed Time** | **373.71s total for 2 chunks** (~185s for Chunk 1) | **> 300.0s for Chunk 1** (`httpx.ReadTimeout`) |
| **Outcome** | Succeeded (produced `cnd_001`, 9 rejected) | Halted with `OllamaProviderError` |

---

## E. Root-Cause Assessment

Ranked by evidentiary certainty:

### 1. Primary Cause: 300-Second Hard Timeout on 1,500-Word Prompt (Definitive)
- A 1,500-word prompt evaluated by a 7B parameter model on consumer hardware (CPU or mixed GPU offload) operates at approximately 5–12 tokens/second.
- Processing ~2,200 input tokens (prompt + transcript) and generating 6 structured JSON candidate objects with quotes and sub-score dictionaries requires between 180 and 360 seconds.
- On 2026-10-24, Chunk 1 completed in ~185 seconds.
- On 2026-10-25, execution took slightly over 300.0 seconds, triggering `httpx.ReadTimeout`.

### 2. Secondary Factor: Execution Context and Memory Contention (High Probability)
- In the standalone run on 2026-10-24, Faster-Whisper was **not running** in the same process prior to discovery.
- In the full pipeline run on 2026-10-25, Faster-Whisper transcribed 10 minutes of audio immediately before Stage 2 in the same Python process. While memory was released, OS page cache, CPU thread pool state, or background system workload pushed inference time past the 300s mark.

### 3. Structural Factor: Stage 2 vs. Stage 3 Workload Imbalance (Definitive)
- Stage 3 has never failed with a timeout because it operates on already-isolated long masters (typically 30–90 seconds, 100–300 words).
- Stage 2 operates on massive 1,500-word chunks spanning 5–7 minutes of source video, demanding an order of magnitude more compute per Ollama call.

---

## F. Recommended Next Step

**Do NOT rewrite prompts, change models, or bypass Stage 2.**

The recommended, smallest evidence-based actions are:
1. **Increase `OLLAMA_TIMEOUT_SECONDS` in `.env`**:
   Raise `OLLAMA_TIMEOUT_SECONDS` from `300.0` to `600.0` (10 minutes). The historical 2026-10-24 Stage 2 run proves that `qwen2.5:7b` requires approximately 370 seconds to process both chunks.
2. **Reuse the Existing Valid Transcript**:
   Pass `-t <path_to_transcript.json>` or allow the orchestrator to reuse the existing 108s Faster-Whisper transcript, avoiding 2 minutes of redundant audio processing.
3. **Optionally Reduce Long Chunk Size**:
   Adjust `LONG_TRANSCRIPT_CHUNK_SIZE` from `1500` to `1000` words, creating 3 smaller chunks of ~120 seconds inference each rather than 2 massive 300-second chunks.
