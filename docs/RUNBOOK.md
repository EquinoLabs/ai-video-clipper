# AI Video Clipper — Operator Runbook

> **Authoritative Operator Manual**  
> **Target Audience:** Terminal operators, creators, and engineers running AI Video Clipper.  
> **Last Updated:** October 2026 | **Version:** 1.0 (Covers Stage 1–4, Staging, Transcript Reuse & Caption Styling v1)

---

## 1. Quick Start

This section provides the fastest path to process a video from start to finish from your terminal.

### 1.1 Fast Path: Single Video End-to-End Run
Run from the **workspace root directory** (`C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`):

```powershell
# 1. Ensure Ollama is running with the required model (in a separate terminal)
ollama serve
ollama pull qwen2.5:7b

# 2. Run the top-level CLI to stage, transcribe, discover, and render final captioned clips
python app.py --single "init_input/sample.mp4" --final --caption-style modern-box
```

### 1.2 Fast Path: Reuse Existing Transcript (Instant Re-run)
If a previous run already generated a valid `transcript.json`, skip Whisper transcription entirely:

```powershell
python app.py --single "init_input/sample.mp4" -t "outputs/2026-10-25/sample_video/run_001_143000/transcript.json" --final --caption-style vibrant-cyan
```

### 1.3 Expected Results
Upon completion, the terminal displays the **Batch Execution Summary** and writes deliverables to:
```
outputs/YYYY-MM-DD/<video_title>/run_NNN_HHMMSS/
├── transcript.json
├── manifest.json
├── long_clips/
│   └── clip_01/
│       ├── clip_01.mp4          # Clean 9:16 vertical master (uncaptioned)
│       ├── clip_01_final.mp4    # Captioned vertical deliverable (if --final)
│       ├── clip_01.ass          # SubStation Alpha subtitle script
│       └── clip_01.srt          # SubRip subtitle script
└── short_clips/
    └── clip_01/
        ├── clip_01.mp4          # Clean 9:16 vertical master (uncaptioned)
        ├── clip_01_final.mp4    # Captioned vertical deliverable (if --final)
        ├── clip_01.ass
        └── clip_01.srt
```

---

## 2. Prerequisites and Environment

Ensure the following system dependencies are installed and available in your environment:

### 2.1 Software Requirements
| Tool | Required Version | Verification Command | Notes |
| :--- | :--- | :--- | :--- |
| **Python** | 3.11+ (3.13 tested) | `python --version` | 64-bit required for faster-whisper C-extensions |
| **FFmpeg** | 6.x+ or 7.x+ | `ffmpeg -version` | **Must have libass enabled** (`--enable-libass`) for subtitle burning |
| **FFprobe** | 6.x+ or 7.x+ | `ffprobe -version` | Bundled with FFmpeg distribution |
| **Ollama** | 0.3+ | `ollama --version` | Local LLM server for candidate discovery |
| **Node.js** | 20.x+ | `node --version` | Required only if running the web review UI |
| **npm** | 10.x+ | `npm --version` | Bundled with Node.js |

> [!IMPORTANT]
> Verify your FFmpeg build supports `libass` by running:
> ```powershell
> ffmpeg -version | Select-String "enable-libass"
> ```
> If empty or missing, install an FFmpeg build that includes `libass` (e.g. Gyan.dev full/essentials build on Windows).

### 2.2 Python Environment Setup
In accordance with project rules, all Python dependencies must reside inside `backend/.venv`:

```powershell
# Open terminal at the project root
cd C:\Lakshya\Coding\EquinoLabs\ai-video-clipper

# Create the virtual environment if it does not already exist
python -m venv backend\.venv

# Activate the virtual environment
# Windows PowerShell:
backend\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source backend/.venv/bin/activate

# Install required dependencies
pip install -r backend\requirements-dev.txt
```

### 2.3 Ollama Local LLM Setup
Candidate discovery defaults to local Ollama (`qwen2.5:7b`):
```powershell
# 1. Start the Ollama server (leave running in a dedicated window or background service)
ollama serve

# 2. Ensure the candidate discovery model is pulled
ollama pull qwen2.5:7b
```

### 2.4 Configuration & Environment Files (`.env`)
Configuration is loaded by Pydantic Settings from `.env` at the root and `backend/.env`.
Ensure `.env` contains:

```ini
ENVIRONMENT=development
LOG_LEVEL=INFO
API_HOST=127.0.0.1
API_PORT=8000

# Whisper ASR Configuration
WHISPER_MODEL=base

# LLM Candidate Discovery Configuration
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT_SECONDS=600.0

# Optional OpenAI fallback (if LLM_PROVIDER=openai)
# OPENAI_API_KEY=sk-proj-your-key-here
# LLM_MODEL=gpt-4o-mini
```

> [!CAUTION]
> Never commit `.env` or files containing API keys, passwords, or cloud credentials to source control.

---

## 3. Application Entry Points

The repository provides several specialized CLI tools and an interactive web interface:

```
                               ┌────────────────────────────────────────────────┐
                               │                    app.py                      │
                               │  Top-Level Staging & Batch Orchestration CLI   │
                               │  (Recommended for almost all operational runs) │
                               └──────────────┬──────────────────┬──────────────┘
                                              │                  │
                         Delegates single /   │                  │ Stages raw
                         batch processing     │                  │ media files
                                              ▼                  ▼
                    ┌───────────────────────────────┐  ┌────────────────────────┐
                    │     orchestrate.py (CLI)      │  │       staging.py       │
                    │   backend/app/cli/orchestrate │  │  Managed input/ storage│
                    └──────────────┬────────────────┘  └────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌────────────────────────┐ ┌────────────────┐ ┌─────────────────────────┐
│    process_local.py    │ │discover_cands  │ │  process_short_clips    │
│  Stage 1: Audio Extract│ │Stage 2: Long   │ │  Stage 3: Short Clips   │
│  & Whisper Transcribe  │ │Candidate Search│ │  from Long Clip Package │
└────────────────────────┘ └────────────────┘ └─────────────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │      render_clips.py (CLI)    │
                    │  Standalone Clip & Captioning │
                    │  Renderer (Phase 3 Tool)      │
                    └───────────────────────────────┘
```

| Entry Point | Invocation Context | Primary Purpose | When to Use |
| :--- | :--- | :--- | :--- |
| **`app.py`** | Project root | Staging, batching, and full pipeline execution | **Primary Operator Tool**. Use for single video runs, folder batches, transcript reuse, and caption styling. |
| **`app.ai_clipper.cli.orchestrate`** | `cd backend` | Low-level Stage 4 orchestration | Advanced pipeline debugging, custom output directory targeting, or skipping rendering (`--no-render`). |
| **`app.ai_clipper.cli.render_clips`** | `cd backend` | Standalone vertical clip & caption rendering | Re-rendering existing candidate moments with different caption presets without rerunning LLM discovery. |
| **`app.ai_clipper.cli.process_short_clips`** | `cd backend` | Stage 3 short clips discovery | Generating short clips from an already generated long master package (`long_clips/clip_XX/`). |
| **`app.ai_clipper.cli.discover_candidates`** | `cd backend` | Stage 2 candidate discovery from transcript | Testing prompt variations, scoring, or candidate boundaries directly from a `transcript.json`. |
| **`app.ai_clipper.cli.process_local`** | `cd backend` | Stage 1 transcription & audio extraction | Transcribing a standalone video file to generate `transcript.json` without running candidate discovery. |
| **`uvicorn app.main:app`** | Project root / `backend` | FastAPI backend server | Launching the local review API (`http://127.0.0.1:8000`). |
| **`npm run dev`** | `frontend/` directory | React review client | Launching the local browser UI (`http://localhost:5173`). |

---

## 4. Complete CLI Reference

### 4.1 `app.py` (Primary Unified CLI)
**Command Syntax:**
```powershell
python app.py (--single VIDEO_FILE | --all FOLDER) [OPTIONS]
```

**Options & Flags:**
| Flag | Short | Value Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `--single` | — | `Path` | *Required (or `--all`)* | Path to a single source video file to stage and process. |
| `--all` | — | `Path` | *Required (or `--single`)* | Path to a directory containing video files to process sequentially. |
| `--transcript` | `-t` | `Path` | `None` | Path to an existing valid `transcript.json` to reuse without re-transcribing (**single video mode only**). |
| `--final` | — | Flag | `False` | Renders final captioned MP4 deliverables (`clip_XX_final.mp4`) with burned subtitles in addition to clean masters. |
| `--caption-style`| — | Choice | `modern-box` | Caption visual preset. Choices: `modern-box`, `classic-outline`, `minimal-shadow`, `vibrant-cyan`, `vibrant-yellow-box`, `vibrant-green`, `vibrant-red`. |
| `--goal` | — | Choice | `overall` | Editorial goal for scoring: `overall`, `humor`, `education`, `emotion`, `thought_provoking`, `hook`, `custom`. |
| `--provider` | — | Choice | Settings (`ollama`) | LLM provider: `ollama` or `openai`. |
| `--model` | — | String | Settings (`qwen2.5:7b`)| LLM model name override. |
| `--input-root` | — | `Path` | `input/` | Managed staging directory where videos and `metadata.json` are stored. |
| `--log-level` | — | Choice | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

**Constraints & Validation Rules:**
- `--single` and `--all` are mutually exclusive. Exactly one must be specified.
- `--transcript` (`-t`) **cannot** be combined with `--all` (a single transcript cannot map to multiple videos). Combining them produces an immediate error and exits with code 1.
- If `--transcript` is provided, the file must exist and be valid JSON, or execution halts before staging.
- If `--caption-style` receives an unlisted choice, `argparse` rejects the input immediately with exit code 2.

---

### 4.2 `app.ai_clipper.cli.render_clips` (Standalone Clip & Subtitle Renderer)
Use this tool to burn captions onto existing candidate moments or render specific candidate IDs without re-running transcription or candidate discovery.

**Command Syntax:**
```powershell
cd backend
python -m app.ai_clipper.cli.render_clips <SOURCE_VIDEO> --candidates <CANDIDATES_JSON> [OPTIONS]
```

**Options & Flags:**
| Argument / Flag | Value Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `source_video` | `Path` (Positional) | *Required* | Path to original source video file (or clean master). |
| `--candidates` | `Path` | *Required* | Path to `candidates.json` artifact containing candidate definitions. |
| `--transcript` | `Path` | `None` | Path to `transcript.json` artifact (required for burning synchronized subtitles). |
| `-o`, `--output-dir` | `Path` | `outputs/rendered_clips/` | Directory where rendered MP4 and subtitle sidecars are written. |
| `--clip-id` | String | `None` | Render only a specific candidate ID (e.g. `cnd_001`). If omitted, renders all candidates in the artifact. |
| `--no-subtitles` | Flag | `False` | Render 9:16 vertical video without burning subtitles. |
| `--caption-style`| Choice | `modern-box` | Caption preset to burn: `modern-box`, `classic-outline`, `minimal-shadow`, `vibrant-cyan`, `vibrant-yellow-box`, `vibrant-green`, `vibrant-red`. |
| `--log-level` | Choice | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

> [!NOTE]
> Unlike early prototype documentation that referenced `--run-dir`, `render_clips.py` in the current codebase strictly requires the positional `source_video` path and the `--candidates` path.

---

### 4.3 `app.ai_clipper.cli.process_short_clips` (Stage 3 Short Discovery & Rendering)
Discovers and renders short clips from an existing long master package directory.

**Command Syntax:**
```powershell
cd backend
python -m app.ai_clipper.cli.process_short_clips <LONG_CLIP_DIR> [OPTIONS]
```

**Options & Flags:**
| Argument / Flag | Value Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `long_clip_dir` | `Path` (Positional) | *Required* | Path to long master package directory (e.g. `outputs/.../long_clips/clip_01/`). |
| `-o`, `--run-dir` | `Path` | Parent run directory | Root run directory where `short_clips/` folder is placed. |
| `-g`, `--goal` | Choice | `overall` | Editorial goal (`overall`, `humor`, `education`, etc.). |
| `-p`, `--provider`| Choice | Settings (`ollama`) | LLM provider: `ollama` or `openai`. |
| `-m`, `--model` | String | Settings (`qwen2.5:7b`)| Model override name. |
| `--timeout` | Float | Settings (`600.0`) | LLM inference timeout in seconds. |
| `--no-render` | Flag | `False` | Discover short candidates without rendering video clips. |
| `--render-final` | Flag | `False` | Render final captioned shorts with burned subtitles. |

---

### 4.4 `app.ai_clipper.cli.orchestrate` (Stage 4 Low-Level Orchestrator)
**Command Syntax:**
```powershell
cd backend
python -m app.ai_clipper.cli.orchestrate <SOURCE_VIDEO> [OPTIONS]
```

**Options & Flags:**
| Argument / Flag | Value Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `source_video` | `Path` (Positional) | *Required* | Path to source video file. |
| `-o`, `--output-dir` | `Path` | Collision-safe date dir | Custom output directory path. |
| `-t`, `--transcript` | `Path` | `None` | Path to valid `transcript.json` to reuse without re-transcribing. |
| `-m`, `--mode` | Choice | `full` | Orchestration mode: `full`, `long`, `short`. |
| `-g`, `--goal` | Choice | `overall` | Editorial goal for scoring. |
| `-p`, `--provider` | Choice | Settings (`ollama`) | LLM provider (`ollama`, `openai`). |
| `--model` | String | Settings | LLM model name override. |
| `--no-render` | Flag | `False` | Discover candidates without rendering clean video masters. |
| `--render-final` | Flag | `False` | Also render final deliverables with burned subtitles. |

---

## 5. Caption Style Presets Guide

The application implements seven registered visual caption presets reverse-engineered from AutoShorts production footage.

### 5.1 Preset Comparison Matrix
| Preset ID | Display Name | Primary Text Color | Border / Box Specification | Recommended Content Tone |
| :--- | :--- | :--- | :--- | :--- |
| **`modern-box`** | Modern Box *(Default)* | `#FFFFFF` (White) | Semi-transparent black box (`&H50000000`), 14px box margin | Professional podcasts, talk shows, balanced readability. |
| **`classic-outline`** | Classic Outline | `#FFFF00` (Yellow) | Heavy 8.0px black outline + 2.0px shadow | Punchy social clips, CapCut style, viral humor. |
| **`minimal-shadow`** | Minimal Shadow | `#FFFFFF` (White) | Thin 1.5px outline + 2.0px subtle drop shadow | Clean aesthetic, cinema, serious interviews, restrained styling. |
| **`vibrant-cyan`** | Vibrant Cyan | `#00FFFF` (Cyan) | 3.0px black outline + 2.0px shadow | Tech, gaming, futuristic, coding commentary. |
| **`vibrant-yellow-box`**| Vibrant Yellow Box | `#000000` (Black) | Solid `#FFFF00` yellow box, 14px box margin | High-contrast TikTok style, bold statement hooks. |
| **`vibrant-green`** | Vibrant Green | `#39FF14` (Neon Green) | 6.5px black outline + 2.0px shadow | High-energy finance, fitness, motivation, Alex Hormozi style. |
| **`vibrant-red`** | Vibrant Red | `#FF3B30` (Neon Red) | 6.5px black outline + 2.0px shadow | High urgency, shocking moments, debate, drama. |

### 5.2 Compatibility Aliases & Safe Fallback
- `default_bold_v1` is retained as a backward-compatibility alias that resolves directly to `modern-box`.
- Underscore variants (e.g. `vibrant_cyan`, `classic_outline`) resolve automatically in code.
- If an unknown or empty style ID is passed programmatically to `get_caption_style()`, the engine falls back safely to `modern-box`.
- When using CLI tools (`app.py` or `render_clips.py`), inputs are strictly validated against the 7 registered IDs.

---

## 6. Common Workflows with Copy-Paste Commands

### Workflow 1: Process One Video End-to-End
Stages the video into `input/YYYY-MM-DD/<video_id>/`, extracts audio, runs Whisper transcription, discovers long and short clips with Ollama, and renders both clean masters and final captioned MP4s:

```powershell
python app.py --single "init_input/interview.mp4" --final --caption-style modern-box
```

### Workflow 2: Process a Video Reusing an Existing Transcript
Fastest workflow when you already have a transcript. Skips Whisper entirely and jumps straight to candidate discovery and rendering:

```powershell
python app.py --single "init_input/interview.mp4" -t "outputs/2026-10-25/interview/run_001_143000/transcript.json" --final --caption-style classic-outline
```

### Workflow 3: Batch Process an Entire Directory of Videos
Sequentially processes all videos found in a directory (supports flat folders or nested hierarchies):

```powershell
python app.py --all "init_input" --final --caption-style modern-box --goal humor
```

### Workflow 4: Re-render Existing Clips with a New Caption Style
Without re-running transcription or discovery, re-render clips from an existing `candidates.json` using `render_clips.py`:

```powershell
cd backend
python -m app.ai_clipper.cli.render_clips "outputs/2026-10-25/interview/run_001_143000/long_clips/clip_01/clip_01.mp4" --candidates "outputs/2026-10-25/interview/run_001_143000/short_clips/candidates.json" --transcript "outputs/2026-10-25/interview/run_001_143000/transcript.json" -o "outputs/2026-10-25/interview/run_001_143000/rendered_clips" --caption-style vibrant-yellow-box
```

### Workflow 5: Render a Single Specific Candidate ID
Render only candidate `cnd_001` with `vibrant-green` captions:

```powershell
cd backend
python -m app.ai_clipper.cli.render_clips "outputs/2026-10-25/interview/run_001_143000/long_clips/clip_01/clip_01.mp4" --candidates "outputs/2026-10-25/interview/run_001_143000/short_clips/candidates.json" --transcript "outputs/2026-10-25/interview/run_001_143000/transcript.json" --clip-id cnd_001 --caption-style vibrant-green
```

### Workflow 6: Generate All 7 Caption Presets for a Video Clip
To generate a complete style showcase of a clip in all 7 presets:

```powershell
$styles = @('modern-box', 'classic-outline', 'minimal-shadow', 'vibrant-cyan', 'vibrant-yellow-box', 'vibrant-green', 'vibrant-red')

foreach ($st in $styles) {
    Write-Host "Rendering style: $st"
    python app.py --single "init_input/interview.mp4" -t "outputs/.../transcript.json" --final --caption-style $st
}
```

### Workflow 7: Run the Interactive Browser Review UI
To browse candidates, play 9:16 vertical previews, inspect evidence quotes, and select caption styles interactively:

**Terminal 1 (Backend API):**
```powershell
cd C:\Lakshya\Coding\EquinoLabs\ai-video-clipper
backend\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 (Frontend Client):**
```powershell
cd C:\Lakshya\Coding\EquinoLabs\ai-video-clipper\frontend
npm run dev
```
Open **`http://localhost:5173`** in your browser.

---

## 7. Input and Output Locations

### 7.1 Input Hierarchy & Staging
- **`init_input/`**: Unmanaged initial intake folder where you place source videos from downloads or cameras.
- **`input/`**: Managed staging directory managed by `staging.py`.
  - Directory structure: `input/YYYY-MM-DD/<video_id>/<normalized_filename>`
  - Alongside each video is a `metadata.json` containing the SHA-256 hash, duration, resolution, and ingestion timestamp.
  - **Deduplication:** When an identical video (matching SHA-256) is ingested on subsequent runs, it is recognized and reused across dates without duplicating storage.

### 7.2 Run Directory Naming Convention
All pipeline run artifacts are saved under `outputs/`:
```
outputs/YYYY-MM-DD/<normalized_video_name>/run_NNN_HHMMSS/
```
- `YYYY-MM-DD`: Execution date in Asia/Kolkata (IST).
- `<normalized_video_name>`: Sanitized title derived from the media metadata.
- `run_NNN_HHMMSS`:
  - `NNN`: Zero-padded sequential run number (`001`, `002`, `003`...) calculated automatically by inspecting existing directories for that video on that date.
  - `HHMMSS`: Execution start timestamp in 24-hour local time.
  - *Backward Compatibility:* Historical directories formatted as `HH_MM_SS__run_NNN` remain intact and are counted when determining the next sequence number.

### 7.3 Deliverables Layout Inside a Run Directory
```
run_NNN_HHMMSS/
├── transcript.json            # Full Whisper transcript with word-level timings
├── manifest.json              # Complete pipeline run manifest (status, media paths, clip list)
├── long_clips/                # Stage 2 Long Conversational Arcs (30s – 180s)
│   ├── candidates.json        # Scored and ranked long candidates
│   ├── clip_01/
│   │   ├── clip_01.mp4        # Clean uncaptioned 9:16 master
│   │   ├── clip_01_final.mp4  # Captioned 9:16 deliverable (if --final)
│   │   ├── clip_01.ass        # Advanced SubStation Alpha subtitle script
│   │   └── clip_01.srt        # SubRip subtitle script
│   └── clip_02/ ...
└── short_clips/               # Stage 3 Short Viral Moments (10s – 60s)
    ├── candidates.json        # Scored and ranked short candidates
    ├── clip_01/
    │   ├── clip_01.mp4        # Clean uncaptioned 9:16 master
    │   ├── clip_01_final.mp4  # Captioned 9:16 deliverable (if --final)
    │   ├── clip_01.ass
    │   └── clip_01.srt
    └── clip_02/ ...
```

---

## 8. Troubleshooting Guide

### 8.1 Common Errors and Resolutions

| Symptom / Error Message | Root Cause | Exact Fix |
| :--- | :--- | :--- |
| **`ModuleNotFoundError: No module named 'app.api'`** | Running a backend CLI module (e.g. `python -m app.ai_clipper.cli...`) from the workspace root where root `app.py` shadows the package. | Either execute `python app.py` (which configures `sys.path`), or `cd backend` before running `python -m app.ai_clipper.cli.<module>`. |
| **`Connection refused` or `httpx.ConnectError` during discovery** | Ollama background daemon is not running. | Run `ollama serve` in a terminal window or start the Ollama desktop service. |
| **`model 'qwen2.5:7b' not found`** | The requested Ollama candidate discovery model has not been downloaded. | Run `ollama pull qwen2.5:7b` to download the model weights. |
| **`ReadTimeout` or `TimeoutError` during Stage 2/3** | Candidate discovery inference took longer than the timeout threshold. | Increase timeout in `.env`: `OLLAMA_TIMEOUT_SECONDS=600.0` or pass `--timeout 600.0`. |
| **`candidates.X.evidence.Y: end_seconds must be greater than start_seconds`** | Raw LLM output produced an inverted evidence timestamp. | Fixed in recent adapter updates: the Ollama adapter sanitizes invalid evidence items individually and logs a warning while keeping valid candidates intact. |
| **`app.py: error: argument --caption-style: invalid choice`** | Passed an unrecognized caption style name. | Choose one of the 7 registered presets: `modern-box`, `classic-outline`, `minimal-shadow`, `vibrant-cyan`, `vibrant-yellow-box`, `vibrant-green`, `vibrant-red`. |
| **`[ERROR] --transcript (-t) cannot be used with --all`** | Tried to map a single transcript file to a multi-video folder batch. | Use `-t` exclusively with `--single <VIDEO_FILE>`. For batch processing, omit `-t` so each video is transcribed individually. |
| **`ffmpeg: No such filter: 'subtitles'` or `libass` error** | The installed FFmpeg binary lacks libass support. | Install a complete FFmpeg build compiled with `--enable-libass` and `--enable-libfreetype` and update `PATH`. |
| **Port 8000 or 5173 already in use** | A previous instance of the API server or Vite is still running. | Backend: `python -m uvicorn app.main:app --port 8001`<br>Frontend: `npm run dev -- --port 5174`. |

### 8.2 Diagnosing Failures Without Destroying Evidence
- **Never delete existing `outputs/` or `input/` folders** to resolve an issue. The pipeline automatically calculates sequential run numbers (`run_001`, `run_002`...) so previous runs and failed attempts are safely preserved.
- **Inspect `manifest.json`**: Check `outputs/.../run_NNN_HHMMSS/manifest.json` to inspect the exact pipeline status, timestamps, and error messages for any failed stage.
- **Increase Verbosity**: Re-run with `--log-level DEBUG` to output full subprocess commands and raw LLM envelopes.

---

## 9. Command Safety and Operation Best Practices

### 9.1 Resource Consumption Guide
- **Expensive Operations:**
  - **Whisper Transcription (Stage 1):** CPU/GPU-intensive audio decoding. Takes 1–3 minutes for a 10-minute video on CPU. Reusing transcripts (`-t`) skips this entirely.
  - **Ollama Candidate Discovery (Stage 2 & 3):** High RAM/VRAM usage. Inference takes 150–400 seconds depending on hardware.
- **Lightweight Operations:**
  - **Video Trimming & Center-Cropping:** Takes ~2–5 seconds per clip using FFmpeg stream processing.
  - **Subtitle Burning (libass):** Takes ~3–6 seconds per 30-second clip.

### 9.2 Safe Scripting Rules
1. **Always verify paths before running:**
   ```powershell
   Test-Path "init_input/video.mp4"
   ```
2. **Use quotes around paths:** Always enclose video and transcript paths in double quotes to handle filenames containing spaces or special characters.
3. **Prefer `app.py` for standard workflows:** It handles path resolution, staging, atomic writes, manifest updates, and directory creation automatically.

---

## 10. Known Limitations

- **Video Framing Mode:** The current pipeline implements 9:16 center-crop framing (Phase 3). Dynamic face-tracking and active speaker detection (Phase 5/6) are non-blocking future enhancements.
- **Batch Transcript Reuse:** `--transcript` is strictly supported for single-video runs (`--single`). Batch runs (`--all`) automatically transcribe each video individually to guarantee transcript-to-media alignment.
- **Font Rendering:** Presets use standard clean fonts (`Arial` / system sans-serif) configured with ASS font sizing, stroke widths, box paddings, and hex color matrices. Custom local TTF font loading is handled transparently by libass.
