# AI Video Clipper

AI Video Clipper is an intelligent video repurposing application designed to transform long-form, speech-heavy videos (podcasts, tutorials, interviews, discussions, commentary) into ranked, reviewable, captioned vertical clips suitable for YouTube Shorts, Instagram Reels, and TikTok.

---

## 1. System Architecture & Boundaries

The application is structured as a **modular monolith** with clean system boundaries:

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                           │
│   React 19 + TypeScript + Vite                              │
│   (Projects, Uploads, Transcript & Candidate Review, UI)    │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON REST
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway / Server                     │
│   FastAPI (Python 3.11+)                                    │
│   - Auth / Project ownership validation                     │
│   - Short-lived presigned upload / download URLs            │
│   - Job submission and status polling                       │
│   - Standardized error envelope { error: { ... } }          │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
               ▼                               ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│      Metadata Storage       │ │     Background Worker       │
│   Neon PostgreSQL           │ │   Python Process (concurrency=1)
│   - Relational metadata     │ │   - Media validation (ffprobe)
│   - Jobs & Stage transitions│ │   - Audio extraction (FFmpeg)
│   - Normalized transcripts  │ │   - Local Whisper transcription
│   - Candidates & Scores     │ │   - Goal-conditioned analysis
│   - Render configurations   │ │   - 9:16 framing & caption render
└─────────────────────────────┘ └──────────────┬──────────────┘
                                               │
                                               ▼
                                ┌─────────────────────────────┐
                                │        Media Storage        │
                                │   Cloudflare R2 (Private)   │
                                │   - Source videos           │
                                │   - Rendered vertical MP4s  │
                                │   - Subtitles (.ass / .srt) │
                                │   - Frame thumbnails        │
                                └─────────────────────────────┘
```

### Key Architectural Decisions

1. **Separation of API and Worker**: Long-running CPU/disk operations (FFmpeg encoding, Whisper transcription, LLM chunk evaluations) never execute inside HTTP request handlers. The API creates jobs, and the worker executes stages asynchronously.
2. **Backend-Owned Versioned Scoring**: The LLM evaluates moments across standardized 0–5 dimensions with transcript quotes; the backend derives durations and computes the authoritative 0–100 overall score using versioned, goal-dependent weights (`v1.0`).
3. **No Direct Video Bytes in DB**: Video media stays strictly in private Cloudflare R2. Database tables store only metadata, object keys, durations, dimensions, and checksums.
4. **Phased Visual Framing**: Default Phase 3 rendering provides solid 9:16 center cropping without requiring heavy computer vision. Face/layout analysis (Phase 5/6) is non-blocking with safe fallbacks (fit-with-background).
5. **Zero Trust for External Providers**: Browser MIME types, user filenames, and LLM timestamps are never trusted directly. Subprocess calls to FFmpeg use sanitized argument arrays with bounded timeouts.

---

## 2. Repository Layout

```
ai-video-clipper/
├── frontend/                     # React + TypeScript + Vite client
│   ├── src/
│   │   ├── config/               # Typed environment variables (env.ts)
│   │   ├── features/             # Feature domain slices
│   │   │   ├── projects/         # Project lifecycle & listing
│   │   │   ├── upload/           # Video upload & probe flow
│   │   │   ├── candidates/       # Candidate moment review & trimming
│   │   │   └── rendering/        # 9:16 rendering, captions & download
│   │   ├── lib/api/              # Typed API client & standard error envelopes
│   │   ├── App.tsx               # Minimal dashboard shell & health monitor
│   │   ├── App.css               # Clean dashboard styles
│   │   └── main.tsx              # Application entrypoint
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── backend/                      # FastAPI API and worker service
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── routes/           # Endpoint handlers (health, etc.)
│   │   │   ├── schemas/          # Pydantic request/response contracts
│   │   │   └── api.py            # API v1 router
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic Settings & environment validation
│   │   │   ├── logging.py        # Structured logging with secret redaction
│   │   │   └── security.py       # Path sanitization, UUID generation
│   │   ├── db/
│   │   │   ├── models.py         # Relational schema reference models
│   │   │   └── repositories/     # Database repository interfaces
│   │   ├── domain/
│   │   │   ├── candidates/       # Candidate scoring engine & goal weights
│   │   │   └── jobs/             # Job state machine & stage tracking
│   │   ├── services/
│   │   │   ├── media/            # FFmpeg & ffprobe discovery & execution
│   │   │   ├── storage/          # StorageProvider interface (R2 / local)
│   │   │   ├── transcription/    # Whisper adapter interface & normalization
│   │   │   ├── llm/              # LLM candidate evaluation adapter interface
│   │   │   └── framing/          # Visual framing & crop window contracts
│   │   ├── workers/
│   │   │   └── worker.py         # Background worker process entrypoint
│   │   └── main.py               # FastAPI application factory & error handling
│   ├── tests/
│   │   ├── unit/                 # Unit tests (config, health, scoring, schemas)
│   │   ├── integration/          # Integration tests
│   │   ├── fixtures/             # Test media fixtures & transcripts
│   │   └── conftest.py           # Shared test fixtures & async test client
│   ├── pyproject.toml            # Project build definition
│   ├── requirements.txt          # Production dependencies
│   ├── requirements-dev.txt      # Dev & testing dependencies
│   └── README.md
├── docs/                         # Specifications & architecture documentation
├── .env.example                  # Root template configuration
├── .gitignore                    # Git ignore for Python, Node, media, secrets
└── README.md                     # Project overview and setup guide
```

---

## 3. Prerequisites

Ensure the following tools are installed on your machine:

- **Node.js**: v20.x or higher (`node --version`)
- **Python**: v3.11 or higher (`python --version`)
- **FFmpeg & FFprobe**: Installed and available in your system `PATH` (`ffmpeg -version`, `ffprobe -version`), built with `libass` and `libfreetype` for subtitle burning.

---

## 4. Getting Started

> [!TIP]
> For the complete, authoritative CLI reference, common operational workflows, transcript reuse, and caption style guide, see the [**Operator Runbook**](docs/RUNBOOK.md). For developer setup and architecture review, see the [Startup & Developer Guide](docs/STARTUP.md).

### Backend Setup

1. **Navigate to the backend directory and create a virtual environment**:
   ```bash
   cd backend
   python -m venv .venv
   ```

2. **Activate the virtual environment**:
   - **Windows (PowerShell)**:
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux**:
     ```bash
     source .venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   ```

5. **Run the End-to-End Pipeline**:
   ```bash
   # Step 1: Ingest & transcribe local video
   python -m app.cli.process_local path/to/video.mp4 --keep-audio

   # Step 2: Discover & score viral candidate clips
   python -m app.cli.discover_candidates outputs/<run_dir>/transcript.json --goal overall

   # Step 3: Render 9:16 vertical clips with burned captions
   python -m app.cli.render_clips path/to/video.mp4 --candidates outputs/<run_dir>/candidates.json --transcript outputs/<run_dir>/transcript.json
   ```

6. **Start the API server**:
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   - Health check: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)
   - Review API runs: [http://127.0.0.1:8000/api/v1/review/runs](http://127.0.0.1:8000/api/v1/review/runs)
   - Interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

7. **Run tests**:
   ```bash
   pytest tests
   ```
   pytest tests
   ```

---

### Frontend Setup

1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Start the Vite development server**:
   ```bash
   npm run dev
   ```
   - Application URL: [http://localhost:5173](http://localhost:5173)

4. **Verify build and type checks**:
   ```bash
   npm run build
   npm run lint
   ```

---

## 5. Implementation Status

- **Phase 1 (Complete)**: Local media ingestion, audio extraction, whole-source Whisper transcription with word timings, source duration boundary clamping, and JSON artifact persistence.
- **Phase 2 (Complete)**: Goal-conditioned candidate discovery, structured 0–5 dimension scoring, versioned 0–100 overall ranking, temporal IoU deduplication, and evidence grounding.
- **Phase 3 (Complete)**: 9:16 vertical center-crop framing, ASS/SRT caption generation with clip-relative timings, FFmpeg render engine with burned subtitles, local Review API endpoints, and React review/playback UI with direct MP4 downloads.
- **Next Phases**:
  - Phase 4: Production database persistence (Neon Postgres) and object storage (Cloudflare R2).
  - Phase 5: Fit-with-background vertical layouts and user caption styling presets.
  - Phase 6: Active speaker tracking and smart crop reframing.
