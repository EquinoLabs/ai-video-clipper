# AI Video Clipper — Startup & Operator Guide

This document is the authoritative startup and developer operations manual for **AI Video Clipper**. It details system prerequisites, environment setup, CLI processing pipelines, API server execution, the local review web application, test suites, and troubleshooting procedures.

---

## 1. System Overview & Architecture

AI Video Clipper operates as a modular monolith designed to ingest speech-heavy video recordings, transcribe spoken audio using faster-whisper, evaluate candidate viral moments using goal-conditioned LLM analysis, crop and frame clips into vertical 9:16 MP4s with burned-in subtitles, and provide a local browser UI for reviewing, previewing, and downloading clips.

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                           │
│   React 19 + TypeScript + Vite (localhost:5173)             │
│   (Run Selection, Ranked Moments, 9:16 Video Player, Export)│
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP REST (CORS enabled)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway / Server                     │
│   FastAPI (127.0.0.1:8000)                                  │
│   - Run listing & candidate metadata endpoints              │
│   - Video streaming & attachment download endpoints         │
│   - Path-traversal sandboxing strictly inside outputs/      │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
               ▼                               ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│      Metadata & Runs        │ │       Media Pipeline        │
│   Local File System         │ │   CLI Tools & Media Engine  │
│   outputs/<run_id>/         │ │   - FFprobe media probe     │
│   - transcript.json         │ │   - FFmpeg 16kHz WAV extract│
│   - candidates.json         │ │   - Faster-Whisper ASR      │
│   - rendered_clips/*.mp4    │ │   - 9:16 center-crop frame  │
│   - rendered_clips/*.ass    │ │   - ASS/SRT caption burning │
└─────────────────────────────┘ └─────────────────────────────┘
```

---

## 2. System Prerequisites

Before starting, ensure your host environment meets the following requirements:

| Tool | Minimum Version | Verification Command | Notes |
|---|---|---|---|
| **Python** | 3.11+ (3.13 tested) | `python --version` | 64-bit required for Whisper C-extensions |
| **Node.js** | 20.x+ | `node --version` | Required for frontend build and Vite server |
| **npm** | 10.x+ | `npm --version` | Bundled with Node.js |
| **FFmpeg** | 6.x+ or 7.x+ | `ffmpeg -version` | **Must include libass and libfreetype** for subtitle rendering |
| **FFprobe** | 6.x+ or 7.x+ | `ffprobe -version` | Bundled with FFmpeg |
| **Git** | 2.40+ | `git --version` | Version control |

> [!IMPORTANT]
> FFmpeg must be present in your system `PATH`. Run `ffmpeg -version` and verify that the configuration flags include `--enable-libass`.

---

## 3. Initial Environment Setup

Follow these steps when setting up the repository on a fresh machine or workspace.

### A. Python Environment (Strict Policy)
In accordance with [`RULES.md`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/RULES.md), all Python dependencies must strictly reside in `backend/.venv`. Never install packages globally.

1. **Open PowerShell / Terminal at the project root**:
   ```powershell
   cd C:\Lakshya\Coding\EquinoLabs\ai-video-clipper
   ```

2. **Create the virtual environment** (if not already created):
   ```powershell
   python -m venv backend\.venv
   ```

3. **Install backend dependencies**:
   ```powershell
   backend\.venv\Scripts\python -m pip install --upgrade pip
   backend\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
   ```
   *(On macOS/Linux, replace `backend\.venv\Scripts\` with `backend/.venv/bin/`)*

4. **Configure environment variables**:
   Create `backend/.env` by copying the template:
   ```powershell
   copy .env.example backend\.env
   ```
   Edit `backend/.env` and provide your OpenAI API key for candidate discovery:
   ```ini
   OPENAI_API_KEY=sk-proj-your-openai-api-key-here
   OPENAI_MODEL=gpt-4o-mini
   ```

### B. Frontend Environment

1. **Navigate to the frontend directory**:
   ```powershell
   cd frontend
   ```

2. **Install Node modules**:
   ```powershell
   npm install
   ```

3. **Return to the root directory**:
   ```powershell
   cd ..
   ```

---

## 4. End-to-End CLI Pipeline

The core processing pipeline can be executed completely via CLI tools before or alongside the web interface.

### Step 1: Ingest & Transcribe Video
Extracts 16 kHz mono speech, generates normalized segment and word-level timestamps clamped strictly to source duration, and persists `transcript.json`:

```powershell
backend\.venv\Scripts\python -m app.cli.process_local "path\to\interview.mp4" --keep-audio
```

**Key Parameters**:
- `-o, --output-dir <path>`: Custom output folder (defaults to `outputs/<media_stem>_<timestamp>`).
- `-m, --model <model>`: Whisper model name (`tiny`, `base`, `small`, `medium`, `large-v3`). Defaults to `base`.
- `-l, --language <code>`: Force ISO language code (e.g., `en`, `es`, `fr`) or auto-detect.
- `--no-word-timestamps`: Emit segment-level timestamps only.
- `--keep-audio`: Preserve the extracted WAV audio file on disk.

*Output Artifact*: `outputs/<run_folder>/transcript.json`

---

### Step 2: Discover & Score Candidate Clips
Analyzes the transcript across editorial dimensions, identifies self-contained moments, calculates 0–100 overall viral scores using goal-dependent weights, and removes overlapping duplicates. Supports local Ollama (`qwen2.5:7b`) and remote OpenAI models:

```powershell
# Option A: Local Ollama model (no API key required)
backend\.venv\Scripts\python -m app.cli.discover_candidates --transcript-file "outputs\<run_folder>\transcript.json" -p ollama -g education

# Option B: OpenAI provider (requires OPENAI_API_KEY)
backend\.venv\Scripts\python -m app.cli.discover_candidates --transcript-file "outputs\<run_folder>\transcript.json" -p openai -g overall
```

**Key Parameters**:
- `--transcript-file <path>`: Path to the generated `transcript.json` (Required).
- `-p, --provider <provider>`: LLM provider: `ollama` or `openai` (defaults to settings `llm_provider`).
- `-g, --goal <goal>`: Target editorial strategy (`overall`, `humor`, `education`, `emotion`, `thought_provoking`, `hook`). Defaults to `overall`.
- `-m, --model <name>`: Model override (`qwen2.5:7b` for Ollama, `gpt-4o-mini` for OpenAI).
- `--ollama-base-url <url>`: Ollama endpoint (defaults to `http://localhost:11434`).
- `--timeout <seconds>`: Request timeout in seconds (defaults to `300.0` for Ollama).
- `--api-key <key>`: Optional command-line API key override (prefers `OPENAI_API_KEY` from `.env`).
- `--iou-threshold <float>`: Temporal IoU deduplication threshold (defaults to `0.50`).

*Output Artifact*: `outputs/<run_folder>/candidates.json`

---

### Step 3: Render 9:16 Vertical Clips with Burned Subtitles
Trims video boundaries, applies 9:16 center-crop framing (`1080x1920`), converts word timestamps into clip-relative ASS/SRT cues, and burns subtitles using FFmpeg libass:

```powershell
# Render all candidates in the run:
backend\.venv\Scripts\python -m app.cli.render_clips --run-dir "outputs\<run_folder>"

# Or render a specific candidate ID:
backend\.venv\Scripts\python -m app.cli.render_clips --run-dir "outputs\<run_folder>" --candidate-id cnd_001
```

*Output Artifacts*:
- `outputs/<run_folder>/rendered_clips/<cand_id>_<start>s_<end>s.mp4`
- `outputs/<run_folder>/rendered_clips/<cand_id>_<start>s_<end>s.ass`
- `outputs/<run_folder>/rendered_clips/<cand_id>_<start>s_<end>s.srt`

---

## 5. Running the Local Review Application

The local web review application allows creators to browse discovered runs, review candidate scores and hooks, inspect spoken evidence quotes, watch 9:16 vertical previews in a mobile viewport, select clips, and download final MP4s.

### Terminal 1: Start Backend API Server
From the repository root:
```powershell
backend\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API Base URL: `http://127.0.0.1:8000/api/v1`
- Review Runs Endpoint: `http://127.0.0.1:8000/api/v1/review/runs`
- Health Status: `http://127.0.0.1:8000/api/v1/health`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

### Terminal 2: Start Frontend Development Server
From the repository root:
```powershell
npm run dev --prefix frontend
```
- Application Web Interface: **`http://localhost:5173`**

### Using the Review UI
1. Open **`http://localhost:5173`** in your browser.
2. The UI automatically connects to the backend and selects the latest processing run from `outputs/`.
3. In the left column:
   - Browse ranked candidate moments with star score badges (e.g. `★ 88`).
   - Check duration, timestamp ranges, and render status badges (`✓ 9:16 Rendered` vs `Not Rendered`).
   - Click **"► View Spoken Evidence & Transcript"** to inspect exact dialogue quotes and context.
   - Use checkboxes to select candidate clips for export or tracking.
4. In the right column:
   - Dedicated 9:16 phone-frame player renders the video with burned-in captions.
   - Seek, play, adjust volume, and inspect full-screen playback.
   - Click **"↓ Download Rendered MP4"** to save the vertical clip directly to your local machine.
5. If new clips were rendered via CLI while the UI is open, click **"Refresh Runs"** in the top toolbar to reload artifacts instantly.

---

## 6. Running Tests & Code Quality Verification

### Run Complete Backend Test Suite
Executes all unit and integration tests (including media extraction, Whisper transcription, scoring, IoU deduplication, timestamp boundaries, and review endpoints):

```powershell
backend\.venv\Scripts\pytest backend\tests -v
```

### Run Live Review Verification Script
Simulates end-to-end API client operations against live output artifacts:

```powershell
backend\.venv\Scripts\python backend\tests\verify_review_live.py
```

### Run Frontend Typecheck, Build & Linter
```powershell
# Oxlint code inspection (0 errors, 0 warnings target)
npm run lint --prefix frontend

# TypeScript typecheck and production bundle build
npm run build --prefix frontend
```

---

## 7. Artifact Directory Structure

All runtime artifacts are strictly isolated inside `outputs/` at the repository root. The API sandbox prevents access outside this folder:

```
outputs/
└── <video_name>_<timestamp>/
    ├── transcript.json            # Whole-source transcript with segment/word timings
    ├── candidates.json            # Ranked candidates with dimension scores & rationale
    ├── extracted_audio_16k.wav    # (Optional) 16 kHz mono WAV audio file
    └── rendered_clips/            # Rendered vertical clips directory
        ├── cnd_001_11.7s_22.8s.mp4 # 9:16 1080x1920 MP4 with burned captions
        ├── cnd_001_11.7s_22.8s.ass # Advanced SubStation Alpha subtitle file
        └── cnd_001_11.7s_22.8s.srt # SubRip subtitle file
```

---

## 8. Common Troubleshooting & FAQs

### Q1: `ffmpeg: command not found` or subtitle errors
- Ensure FFmpeg is installed and added to your system `PATH`.
- Check if your FFmpeg build supports libass by running:
  ```powershell
  ffmpeg -version | Select-String "enable-libass"
  ```
- If missing, install an FFmpeg build that includes libass (e.g. `gyan.dev` full build on Windows or `brew install ffmpeg` on macOS).

### Q2: PowerShell says `running scripts is disabled on this system`
If activating `.venv\Scripts\Activate.ps1` produces an execution policy error, bypass it for the current process:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Or invoke Python directly without activating:
```powershell
backend\.venv\Scripts\python.exe <command>
```

### Q3: Candidate discovery reports `OpenAI API key not configured`
Ensure `OPENAI_API_KEY` is defined in `backend/.env` or passed via `--api-key`:
```powershell
backend\.venv\Scripts\python -m app.cli.discover_candidates --transcript-file outputs/<run>/transcript.json --api-key "sk-proj-..."
```

### Q4: Port 8000 or 5173 is already in use
- **Backend**: Specify a custom port with `--port`:
  ```powershell
  backend\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
  ```
  *(Remember to update `VITE_API_BASE_URL=http://localhost:8001/api/v1` in `frontend/.env`)*
- **Frontend**: Vite will automatically offer port `5174` or you can launch with `npm run dev -- --port 5174`.
