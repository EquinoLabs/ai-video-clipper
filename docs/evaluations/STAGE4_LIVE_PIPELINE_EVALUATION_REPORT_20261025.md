# Stage 4 Live End-to-End Pipeline Evaluation Report — Strict Read-Only Mode

**Evaluation Date**: 2026-10-25  
**Execution Mode**: Single-Video Pipeline Execution (`--final --single`)  
**Pipeline Entry Point**: `app.py`  
**Execution Environment**: Windows PowerShell / Python 3.13.2 (`backend/.venv`)  
**Strict Safety Mode**: READ-ONLY. Zero code edits, zero configuration changes, zero manual retries, zero artifact cleanup.

---

## 1. Executive Summary & Verdict

### **Overall Verdict: FAIL (CONFIGURATION PREREQUISITE DEFECT)**

- **Failure Type**: Environment / Default Provider Configuration.
- **Root Cause**: The default LLM provider in `backend/app/core/config.py` is configured as `llm_provider: str = "openai"` and `llm_model: str = "gpt-4o-mini"`. When invoking `app.py --final --single <video>` without an explicit `--provider` flag, the pipeline defaulted to OpenAI. In Step 3 (Long-Clip Candidate Discovery), the OpenAI adapter attempted to read `OPENAI_API_KEY`, which was unset in the environment, causing an immediate `OpenAIProviderError: OpenAI API key not configured`.
- **What Succeeded Before the Failure**:
  1. **Input Staging (Step 1)**: Executed flawlessly. The 133 MB raw video in `init_input/` was verified, probed, and staged atomically into `input/anne_hathaway_forgets_the_princess_diaries_and_the_devil_wears_prada_details_chats_the_idea_of_you_the_tonight_show_starring_jimmy_fallon_1080p_h264.mp4` with a matching ingestion metadata JSON file. The original in `init_input/` was untouched.
  2. **Transcription Pipeline (Step 2)**: Executed flawlessly end-to-end. Audio stream 0 was extracted to 16 kHz mono WAV (19.01 MB), Faster-Whisper loaded `base` model, and transcribed the entire 10-minute 22-second video (622.84s) in 106.03s, producing 334 timestamped segments with word timings (`381,719` bytes JSON artifact).
  3. **Run Isolation & Manifest Persistence**: A dedicated collision-safe directory was created under `outputs/2026-10-25/.../01_51_02__run_001/`. The run manifest recorded accurate stage statuses (`transcription: completed`, `long_discovery: running`, `status: failed`) and captured the error message.
- **Per Strict Rule**: No code was edited, no flags were changed to bypass the failure, no files were cleaned up, and no second run was launched.

---

## 2. Pre-Run Inspection & Recorded Baseline

### Source Media in `init_input/`:
- **Filename**: `Anne Hathaway Forgets The Princess Diaries and The Devil Wears Prada Details, Chats The Idea of You - The Tonight Show Starring Jimmy Fallon (1080p, h264).mp4`
- **File Size**: `133,058,509` bytes (~126.89 MB)
- **Container Duration**: `622.839002` seconds (~10 min 22 sec)
- **Streams**: 1 Video stream (h264, 1920x1080), 1 Audio stream (aac, 44100 Hz, stereo)
- **SHA-256 Hash**: `6CF414FCDAE21D2ECF3C8931015C3148915DDD27F42CDAACAAD92415C46379C2`

### Pre-Run Directory Check:
- `input/`: Confirmed **empty** before execution.
- Baseline Candidate Hash (`outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`):
  `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (Confirmed intact).

---

## 3. Exact Execution Details

### Command Executed:
```powershell
backend\.venv\Scripts\python.exe app.py --final --single "init_input/Anne Hathaway Forgets The Princess Diaries and The Devil Wears Prada Details, Chats The Idea of You - The Tonight Show Starring Jimmy Fallon (1080p, h264).mp4"
```

### Execution Metrics:
- **Process Exit Code**: `1`
- **Start Time**: 2026-10-25 01:51:02 IST
- **End Time**: 2026-10-25 01:54:33 IST
- **Elapsed Duration**: `210.72` seconds (~3.5 minutes)
- **Run ID**: `run_01_51_02__run_001`
- **Run Directory**: `outputs/2026-10-25/anne_hathaway_forgets_the_princess_diaries_and_the_devil_wears_prada_details_chats_the_idea_of_you_the_tonight_show_starring_jimmy_fallon_1080p_h264/01_51_02__run_001`
- **Batch Summary File**: `outputs/batch_logs/batch_20261024_202102__summary.json`

---

## 4. Stage-by-Stage Findings & Artifact Inspection

### 4.1 Input Staging
- **Staged File**: `input/anne_hathaway_forgets_the_princess_diaries_and_the_devil_wears_prada_details_chats_the_idea_of_you_the_tonight_show_starring_jimmy_fallon_1080p_h264.mp4` (`133,058,509` bytes).
- **Metadata File**: `input/anne_hathaway_forgets_the_princess_diaries_and_the_devil_wears_prada_details_chats_the_idea_of_you_the_tonight_show_starring_jimmy_fallon_1080p_h264__metadata.json` (1,603 bytes).
- **Integrity**: Original source file in `init_input/` remained bit-for-bit identical (SHA-256 unchanged).

### 4.2 Probing & Audio Extraction
- **Audio Stream**: Extracted to 16 kHz mono WAV (`19.01 MB`) inside the run folder.
- **Probe Details**: 622.84s duration, 1 video stream, 1 audio stream. Cleanly cleaned up after transcription completed.

### 4.3 Transcription Stage
- **Engine**: Faster-Whisper (`base` model, int8 on CPU).
- **Duration**: `106.03` seconds.
- **Artifact**: `outputs/2026-10-25/.../01_51_02__run_001/transcript.json` (`381,719` bytes).
- **Content**: 334 segments, English language (probability: `0.998`), word-level timings enabled and fully populated.
- **Sample Excerpt**:
  - `[0.10s - 4.14s]`: *"Thank you for playing reverse charades with me. You're a great partner. Thank you. You're a partner"*
  - `[4.14s - 8.72s]`: *"I mean, are you are you competitive when you play games? Do you play games at home in to be?"*
- **Status**: **STAGE COMPLETED SUCCESSFULLY**.

### 4.4 Long-Clip Candidate Discovery (Stage 2)
- **Transcript Chunking**: Partitioned into 2 chunks (`target_words=1500`, `overlap=60.0s`).
  - Chunk 1/2: `[0.1s - 410.8s]`, words=1507.
  - Chunk 2/2: `[350.2s - 622.8s]`.
- **LLM Provider Instantiation**: The CLI invoked `run_candidate_discovery(mode="long")` which read `settings.llm_provider` (`"openai"`) because no `--provider` argument was provided on the CLI command.
- **Exception Raised**:
  ```text
  app.services.llm.openai_adapter.OpenAIProviderError: OpenAI API key not configured. Set OPENAI_API_KEY in environment or .env.
  ```
- **Error Propagation**: The orchestrator captured the exception, logged the traceback, updated `manifest.stage_statuses["long_discovery"] = "running"`, appended the error to `manifest.errors`, set `manifest.status = "failed"`, and serialized `manifest.json`.

### 4.5 Shorts Discovery & Final Deliverable
- Because Stage 2 failed during candidate discovery, zero long clips were rendered (`long_clips: []`).
- Stage 3 short discovery was not initiated (`short_discovery: pending`).
- Final burned-subtitle deliverables (`--final`) were not rendered because no candidate clips reached the rendering stage.

---

## 5. Artifact & Manifest Verification

- **Manifest Path**: `outputs/2026-10-25/anne_hathaway_forgets_the_princess_diaries_and_the_devil_wears_prada_details_chats_the_idea_of_you_the_tonight_show_starring_jimmy_fallon_1080p_h264/01_51_02__run_001/manifest.json`
- **Manifest Content**:
  ```json
  {
    "schema_version": "v1.0",
    "run_id": "run_01_51_02__run_001",
    "status": "failed",
    "configuration": {
      "editorial_goal": "overall",
      "llm_provider": "openai",
      "llm_model": "gpt-4o-mini"
    },
    "stage_statuses": {
      "transcription": "completed",
      "long_discovery": "running",
      "short_discovery": "pending"
    },
    "long_clips": [],
    "short_clips": [],
    "errors": [
      "OpenAI API key not configured. Set OPENAI_API_KEY in environment or .env."
    ]
  }
  ```
- **Consistency**: The manifest accurately reflects the failed run status and captures the exact error reason. No partial or corrupt clips were marked valid.

---

## 6. Final Integrity Check

1. **Source in `init_input/`**:
   - SHA-256: `6CF414FCDAE21D2ECF3C8931015C3148915DDD27F42CDAACAAD92415C46379C2` (**CONFIRMED UNCHANGED**).
2. **Pre-existing artifacts in `outputs/`**:
   - Baseline hash for `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`:
     `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (**CONFIRMED UNCHANGED**).
3. **Pre-existing artifacts in `experimental_output/`**:
   - Confirmed zero modifications or deletions.
4. **Source Code & Configuration**:
   - Zero files modified, deleted, or altered.

---

## 7. Recommended Next Action

The pipeline is technically sound up to Stage 2 LLM discovery: audio extraction, media probing, Faster-Whisper transcription, transcript slicing, and atomic staging all passed with zero errors.

The failure was strictly due to the default configuration requesting OpenAI when no `OPENAI_API_KEY` was configured in the environment.

**Recommended Action**:
Run the evaluation with the local Ollama provider explicitly specified, or configure `OPENAI_API_KEY`:
```powershell
python app.py --final --provider ollama --model qwen2.5:7b --single "init_input/Anne Hathaway Forgets The Princess Diaries and The Devil Wears Prada Details, Chats The Idea of You - The Tonight Show Starring Jimmy Fallon (1080p, h264).mp4"
```
*(Awaiting user authorization before any further action; no fixes or reruns were executed).*
