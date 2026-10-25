# AI Video Clipper — Backend

FastAPI backend service and asynchronous worker pipeline for AI Video Clipper.

## Architecture

- **Framework**: FastAPI (Python 3.11+)
- **API Spec**: OpenAPI / Swagger (`/docs`)
- **Metadata Database**: Neon Postgres (relational metadata, jobs, stage tracking, transcripts, candidates)
- **Object Storage**: Cloudflare R2 (source videos, rendered clips, captions, thumbnails)
- **Media Engine**: FFmpeg and ffprobe (audio extraction, probing, vertical cropping, caption burning)
- **Transcription**: Local Whisper provider adapter
- **Candidate Evaluation**: LLM adapter with goal-conditioned scoring and strict Pydantic schema validation

## Repository Layout

```
backend/
  app/
    api/
      v1/
        routes/        # Route handlers (health, projects, jobs, candidates)
        schemas/       # Pydantic request/response contracts
        api.py         # Router aggregation
    core/
      config.py        # Pydantic Settings & environment variables
      logging.py       # Structured logging & secret redaction
      security.py      # Path sanitization, token signing, ID generation
    db/
      models.py        # Database schema definitions
      repositories/    # Data access layer
    domain/
      jobs/            # Job state machine & stage boundaries
      candidates/      # Candidate scoring & ranking logic
    services/
      storage/         # Cloudflare R2 / storage provider interface
      transcription/   # Whisper adapter interface
      llm/             # LLM discovery & scoring adapter interface
      media/           # FFmpeg / ffprobe wrappers
      framing/         # Visual analysis & vertical reframing
    workers/
      worker.py        # Background worker process
    main.py            # FastAPI app factory and lifecycle
  tests/
    unit/              # Unit tests for config, routes, schemas, scoring
    integration/       # Pipeline and provider integration tests
    fixtures/          # Test media and transcript samples
  pyproject.toml       # Build definition and dependencies
  requirements.txt     # Pinned production requirements
  requirements-dev.txt # Development and testing requirements
  .env.example         # Template environment configuration
```

## Setup & Running Locally

### 1. Create and Activate Virtual Environment

```bash
cd backend
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# macOS/Linux:
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements-dev.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in necessary keys:
```bash
cp .env.example .env
```

### 4. Run the Phase 1 Local Pipeline (CLI)

Process a local video file (probe streams, extract 16 kHz mono WAV, transcribe with local Whisper, save normalized `transcript.json`):

```bash
python -m app.ai_clipper.cli.process_local path/to/video.mp4 -m tiny --keep-audio
```

Options:
- `-o, --output-dir`: Custom output folder (defaults to `outputs/<file>_<timestamp>`)
- `-m, --model`: Whisper model name (`tiny`, `base`, `small`, `medium`, `large-v3`)
- `-l, --language`: Force language code (e.g. `en`, `es`) or auto-detect
- `--no-word-timestamps`: Output segment timestamps only
- `--keep-audio`: Preserve the extracted 16 kHz mono WAV file on disk
- `--log-level`: Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

### 5. Start the API Server

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API Health: `http://127.0.0.1:8000/api/v1/health`
- Interactive API Docs: `http://127.0.0.1:8000/docs`

### 6. Run Tests

```bash
pytest
```
