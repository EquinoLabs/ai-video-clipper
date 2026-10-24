# Stage 4 Follow-up: Input Staging & Batch Runner Completion Report

**Date**: 2026-10-25  
**Milestone**: Input Staging, Batch Runner, and Root CLI Entry Point (`app.py`)

---

## 1. Executive Summary

As a follow-up to Stage 4 orchestration, a clean, backend-only entry point has been implemented to simulate UI uploads and automate batch execution across single files or folders of video inputs.

### Core Capabilities Delivered:
1. **`init_input/` Working Directory**: Created as the root folder where original testing videos are placed manually.
2. **Safe Atomic Input Staging (`backend/app/services/storage/staging.py`)**:
   - Validates existence, regular file status, decodable video streams (via ffprobe), and supported video extensions (`.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`).
   - Copies files into `input/` atomically using a temporary file pattern, never modifying or renaming the source in `init_input/`.
   - Assigns normalized, collision-safe filenames (`name_2.mp4`, `name_3.mp4`) to avoid overwriting existing staged assets.
   - Saves ingestion metadata (`*__metadata.json`) capturing the original filename, content hash, and stream info.
3. **Failure-Isolated Batch Runner (`backend/app/services/pipeline/batch_runner.py`)**:
   - Executes videos sequentially in deterministic alphabetical order.
   - Isolates failures: if a video fails staging or pipeline processing, subsequent videos continue uninterrupted.
   - Emits structured per-video diagnostic summaries and persists a comprehensive JSON summary in `outputs/batch_logs/`.
   - Returns a non-zero exit code if any video fails, and exit code `0` if all succeed or are cleanly skipped.
4. **Target CLI Interface (`app.py`)**:
   - Created at project root per user specification, supporting `--single` and `--all` modes, with `--final` to trigger burned subtitle deliverables.

---

## 2. Command Reference

### Process a Single Video:
```powershell
backend\.venv\Scripts\python.exe app.py --final --single "init_input/Anne Hathaway.mp4"
```

### Process Every Supported Video in a Folder:
```powershell
backend\.venv\Scripts\python.exe app.py --final --all "init_input"
```

### Additional Supported Options:
- `--final`: Renders final deliverable MP4s (`clip_XX_final.mp4` with burned subtitles) in addition to clean 9:16 vertical masters.
- `--goal`: Configures the editorial goal (`overall`, `humor`, `education`, `emotion`, etc.). Default: `overall`.
- `--provider`: Specifies the LLM provider (`ollama` or `openai`).
- `--model`: Specifies the model name (e.g. `qwen2.5:7b`).
- `--input-root`: Managed staging destination folder (default: `input/`).
- `--log-level`: Logging verbosity level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

---

## 3. Input Staging & Filename Policy

1. **Non-Destructive Source Guarantee**:
   - Files inside `init_input/` are opened read-only and copied via `shutil.copyfile` and `shutil.copystat`.
   - Never renamed, moved, or deleted.
2. **Collision Safety in `input/`**:
   - Filenames are normalized to lowercase snake_case (e.g. `"Anne Hathaway (1080p).mp4"` $\to$ `"anne_hathaway_1080p.mp4"`).
   - If an asset with the same name already exists in `input/`, it is suffixed deterministically (`_2`, `_3`, etc.) to guarantee no overwrite.
3. **Atomic Staging**:
   - Copies write to `.staging_<name>_<hash>.<ext>` first, and are atomically promoted via `os.replace`. Partial copies are never exposed to the pipeline.

---

## 4. Batch & Item Status Semantics

- **`completed`**: Source video was staged and all pipeline stages (probing, transcription, Stage 2 long discovery, and Stage 3 short discovery) finished successfully.
- **`failed`**: Video staging failed (e.g. missing, corrupt, non-video) or the orchestrator encountered an unrecoverable pipeline error. Recorded in `summary.failed_videos` and causes a non-zero exit code.
- **`skipped`**: Non-video files or directories (e.g. `.txt`, `.DS_Store`) encountered in `--all` mode. Skipped with a warning; does not fail the batch.
- **Valid Zero Results**: A run where the LLM proposes 0 long clips or 0 short clips is treated as `completed` (valid benign outcome), with `long_clips_count=0` or `short_clips_count=0`.

---

## 5. Testing & Verification

Comprehensive unit tests implemented in [`backend/tests/unit/test_staging_and_batch_runner.py`](file:///C:/Lakshya/Coding/EquinoLabs/ai-video-clipper/backend/tests/unit/test_staging_and_batch_runner.py):
1. **`test_is_supported_video_file`**: Verifies extensions `.mp4`, `.mov`, `.mkv` are accepted and `.txt`, folders are rejected.
2. **`test_stage_input_video_preserves_original_and_assigns_collision_safe_name`**: Verifies original file remains intact, first copy stages cleanly, and a duplicate file with the same name receives `_2.mp4` without overwriting.
3. **`test_stage_input_video_rejects_empty_or_unsupported`**: Verifies 0-byte files and unsupported formats fail staging gracefully.
4. **`test_batch_runner_processes_folder_in_deterministic_order`**: Verifies files are processed in alphabetical order (`apple` $\to$ `banana` $\to$ `zebra`) and non-video files are skipped.
5. **`test_batch_runner_isolates_failure_and_continues`**: Verifies that when video 1 fails with an exception, video 2 runs to completion, and the batch returns exit code `1`.

### Test Suite Execution:
- `backend/tests/unit/test_staging_and_batch_runner.py`: **5 passed in 0.27s**.
- Full Backend Unit Suite (`backend/tests/unit/`): **147 passed in 1.45s** (100% pass rate).

---

## 6. Protection of Existing Artifacts

- **Baseline Hash Verified**:
  - File: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`
  - SHA-256: `40474A9EA98A665C4AE1CE14703F1C6FFA04661952D9577F9A06FABE76E494FE` (**CONFIRMED UNCHANGED**).
- **Existing Directories**: Zero modifications or deletions inside `input/`, `outputs/`, or any `experimental_output/` folders.

---

## 7. Recommended Next Step

With input staging, sequential batch running, and root CLI invocation (`app.py`) complete and verified, the next implementation milestone is building the FastAPI review/run trigger endpoints in `backend/app/api/v1/routes/review.py` and `jobs.py`.
