# AI Animation Studio: PRD and Architecture

Oct 25, 2026

## 1. Overview

A second feature in the existing `ai-video-clipper` repo. The user describes a topic in a chat UI, the AI co-writes a structured script, the user approves it, and the system produces a finished explainer video: simple animated characters (stick-figure style), AI voiceover, scenes with backgrounds and props, captions, and music. All content is original, so there is no third-party footage and no reused-content risk. Reference style: calm, motivating, simple-explanation channels (similar to Psych2Go). Characters and art must be original, not copies of any existing channel's designs.

Target: 5 to 10 minute videos (ideal), 30 minutes maximum. Personal project for now, not shipped.

## 2. Goals and non-goals

**Goals**

- Chat-driven script creation with a hard Finalize gate: nothing downstream runs until the script is approved.
- Script structure rules enforced: hook, setup, middle, climax, takeaway. Plain, non-exaggerated tone.
- Scene planner that reports which assets are reusable from the asset pack and which are missing.
- Code-animated characters (layered SVG parts, poses, expressions) rendered on CPU, so the 6 GB GPU is only needed for LLM, TTS and transcription stages.
- Per-scene rendering so one scene can be re-rendered without redoing the video.
- Zero disruption to the existing clipper.

**Non-goals for v1**

- AI-generated video or images, consistent AI characters, realistic faces or real people.
- Multi-user accounts, billing, public deployment.
- Walk cycles and complex object interaction (preset actions only).

## 3. User flow

1. **Brief:** user chats about topic, audience, length, tone.
2. **Outline:** AI proposes an outline (hook, sections, climax). User edits and approves.
3. **Script:** AI writes section by section. User edits in chat or directly. **Finalize Script** locks it (versioned, immutable after lock).
4. **Scene plan:** AI splits the script into scenes and beats and picks layout, characters, poses, expressions, actions, backgrounds, props from the asset manifest.
5. **Coverage report:** per scene: reuse, substitute, or missing, plus a ranked list of missing assets and which scenes need them. User fixes gaps by adding assets, accepting substitutes, or asking for a scene rewrite.
6. **Voiceover:** TTS per beat, durations measured.
7. **Render:** per-scene animation, joined with ffmpeg, captions from TTS word timings, background music, final encode.
8. **Review:** play the video, change a line or pose, re-render only that scene.

## 4. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-1 | Script chat: multi-turn session, stored history, structured system prompt with story-structure rules. |
| FR-2 | Long scripts are generated outline-first, then per section, with a running summary passed forward to keep consistency. |
| FR-3 | Finalize gate: scene planning refuses to start on a non-finalized script. |
| FR-4 | Asset manifest (JSON): id, type (background, prop, character, pose, expression, action), tags, description, file path. Validated on load. |
| FR-5 | Scene plan JSON: beats with narration, layout, characters, pose, expression, action, background, props, camera. Every referenced id must exist in the manifest (validated in code, retry on failure). |
| FR-6 | Coverage report: reuse / substitute / missing per scene, with missing-asset specs saved to a backlog file. |
| FR-7 | TTS adapter interface (local Kokoro or Piper first, paid voice swappable). Synthesis per beat, with pauses joined by ffmpeg. |
| FR-8 | Character system: layered SVG parts, pose = joint angles, expression = face swap, mouth open/close driven by audio. Stick figure first. |
| FR-9 | Renderer: scene JSON plus audio in, scene MP4 out. Scenes cached by content hash. |
| FR-10 | Captions generated from TTS word timings (reuse existing ASS subtitle code). |
| FR-11 | Resumable runs: every stage writes artifacts and a run manifest, rerun skips completed stages. |
| FR-12 | LLM provider chosen per step (local Ollama for cheap structured work, Claude for script quality), with fallback. |

## 5. Data contracts (the interfaces between parts)

These JSON schemas are the contracts that let separate people or agents work in parallel. Changing one needs agreement from both sides.

- `script.json`: title, structure sections, narration text per section, status (draft or final), version.
- `asset_manifest.json`: list of assets as in FR-4.
- `scene_plan.json`: ordered scenes, each with ordered beats (see FR-5).
- `coverage_report.json`: per scene status, missing-asset specs.
- `animation_run_manifest.json`: stage statuses, artifact paths, durations, hashes.

Example beat:

```json
{
  "id": "s03_b02",
  "narration": "Most people never notice this habit.",
  "scene": {
    "layout": "two_shot",
    "background": "bg_office_01",
    "characters": [
      {"id": "narrator", "pose": "point", "expression": "curious"},
      {"id": "bystander_1", "pose": "idle", "expression": "neutral"}
    ],
    "props": ["prop_laptop_01"],
    "action": "none",
    "camera": "zoom_in"
  }
}
```

## 6. What the existing repo looks like

Findings from reading `backend/` (the repo is a modular monolith, FastAPI plus a worker, React frontend under `frontend/src/features/*`).

**Directly reusable by the animation feature**

- `core/` (config, logging, security) and the standard error envelope in `api/v1/schemas/common.py`.
- `services/media/` (ffmpeg runner, probing, extraction, ASS/SRT subtitle generation). Subtitles take transcript segments with word timings, so TTS timings can be converted into that format.
- `services/storage/` (output manager, staging).
- `services/llm/` factory and Ollama and OpenAI adapters, with caveats below.
- `main.py` app factory, request-ID middleware, CORS.

**Clipper-specific, animation must not depend on these**

- `services/candidates/`, `services/pipeline/` (orchestrator, long and short pipelines), `services/framing/`, `services/rendering/` (long and short clip renderers), `api/v1/routes/review.py`, `domain/candidates`, `domain/manifest`, clipper CLI files.

**Things to know before sharing code**

1. `LLMProvider` has one abstract method, `discover_and_evaluate`, shaped for clip discovery, and `llm/base.py` imports from `api/v1/schemas/candidates`. Do not add abstract methods to it (it would break existing adapters and tests). Add a separate generic structured-output interface instead.
2. `core/config.py` is one flat `Settings` class. Do not add animation fields to it. Give animation its own settings class.
3. The review router serves anything under `outputs/`, relative to the working directory. Animation runs must not write there, or the clipper's run listing may pick them up.
4. `db/models.py` and `workers/worker.py` are currently documentation and a stub, so the pipeline is file-based and run through CLI and orchestrator. Animation should follow the same file-based, manifest-driven style for now.
5. `requirements.txt` has no TTS, Playwright or image libraries yet. Per `RULES.md`, install only into `backend/.venv` and keep requirements files in sync.

## 7. Proposed architecture

### 7.1 Backend layout (additive, no moves in phase 0)

```
backend/app/
  core/                  existing, shared
  services/media|storage|llm   existing, shared (read-only for animation)
  common/                NEW: only code both features need
    llm/structured.py      generate_json(prompt, schema, provider) over existing factory config
    tts/                   TTS interface + adapters (may start inside animation/)
  animation/             NEW: everything animation-specific
    config.py              AnimationSettings (env prefix ANIM_)
    domain/                script, scene plan, asset manifest, run manifest models
    services/
      scriptwriter/        chat session, outline, section writing, finalize gate
      planner/             scene planning, asset coverage report
      assets/              manifest loading, validation, tag search
      tts/                 per-beat synthesis, duration measurement
      characters/          SVG parts, poses, expressions, lip movement
      renderer/            scene renderer (Playwright or Cairo), scene cache
      pipeline/            orchestrator for animation runs
    api/                   routes.py, schemas.py (mounted under /api/v1/animation)
    cli/                   run_animation.py
  api/v1/api.py          existing: add one include_router line
tests/
  animation/             NEW, separate from existing unit and integration tests
assets/animation/        NEW: character parts, backgrounds, props, manifest, music
animation_outputs/       NEW: run artifacts, kept apart from outputs/
```

### 7.2 Phase 1 (later, optional): tidy the clipper

Once animation is stable, move clipper-only code into `app/clipper/` with `git mv`, update imports, and run the existing test suite as the safety net. Do this as its own change, never mixed with feature work.

### 7.3 Dependency rules

- `animation` may import `core`, `common`, and the shared services (`media`, `storage`, `llm`).
- `clipper` code may import `core`, `common`, shared services. It must never import `animation`.
- `animation` must never import clipper-only modules (candidates, pipeline, framing, clip renderers).
- Shared modules change only additively, with the existing tests passing.
- Enforce with a small test that scans imports (or import-linter), so a violation fails CI instead of relying on discipline.

### 7.4 Frontend

Start inside the existing Vite app as a new feature slice, `frontend/src/features/animation/` (script chat, scene plan and coverage view, asset manager, render review), mounted on its own route, reusing the typed API client in `lib/api`. This matches the repo's current `features/*` structure and avoids a second toolchain. If the two UIs diverge, split later into a separate app that reuses the same client.

### 7.5 Working in parallel

| Lane | Owns (only edits here) | Talks to others through |
| --- | --- | --- |
| Clipper | existing clipper code and \`tests/unit | integration\` |
| Animation backend | `app/animation/`, `tests/animation/`, `assets/animation/` | the JSON contracts in section 5, the API schemas |
| Animation frontend | `frontend/src/features/animation/` | OpenAPI schema from the animation routes |
| Shared (rare) | `core/`, `common/`, shared services | small, additive changes reviewed by both lanes |

Working rules: one branch per lane, a CODEOWNERS file for the folders above, contract changes made in their own small commit, and stub or mock implementations behind each interface so lanes can build without waiting on each other (for example a fake TTS that emits silence of the right length, a fake LLM that returns a canned scene plan).

## 8. Non-functional requirements

- Hardware: 6 GB VRAM laptop GPU, 16 GB RAM. GPU stages run one at a time and unload models between stages (for example Ollama `keep_alive: 0`).
- Rendering is CPU-based and per scene. Use `h264_nvenc` for the final encode if available.
- Deterministic and resumable: same inputs give same scene hash, finished scenes are skipped.
- All LLM output is validated against schemas, with bounded retries and a local fallback model.
- Subprocess calls use argument arrays and timeouts, matching the repo's existing zero-trust conventions.

## 9. Milestones

| # | Milestone | Done when |
| --- | --- | --- |
| M0 | Scaffold: `animation/` package, settings, route stub, test folder, import-rule test, empty manifests | Existing test suite still passes; new package imports cleanly |
| M1 | Render prototype: hand-written 30 s script, TTS, one stick-figure narrator (3 poses, 3 expressions), one background, captions | A watchable MP4 is produced from the CLI |
| M2 | Scene plan and coverage report from a short script, validated against the manifest | Invalid asset ids are rejected and retried; coverage JSON generated |
| M3 | Script chatbot with outline-first flow and Finalize gate (API plus UI) | Planner refuses a non-final script |
| M4 | Second and third characters, props, 20 backgrounds, camera moves, per-scene re-render | A 5-minute video end to end |
| M5 | Review UI, music mixing, polish, 10-minute run | Re-render one scene from the UI |

## 10. Risks and open questions

- **Asset volume** is the long-term bottleneck. Mitigate with the coverage report, icon packs with permissive licenses, and scripts steered toward what the library supports.
- **Visual monotony** over 5 to 10 minutes. Needs scene variety, camera moves, text callouts, cutaway diagrams.
- **Script quality** from a 7B local model. Use Claude for scripting and review factual claims before finalizing, especially for psychology or health topics.
- **Render time**: about 18,000 frames for 10 minutes at 30 fps. Consider 24 fps and caching.
- **Voice licensing** if the videos are monetized. Check each TTS model's license.
- Open: Playwright (HTML/SVG) versus Python drawing for the renderer. Decide in M1 by timing a 30-second scene.
- Open: where the user wants the asset pack stored long term (in repo versus separate storage).

## 11. Complexity summary

| Area | Difficulty |
| --- | --- |
| Script chatbot and Finalize gate | Easy to medium |
| Long-script generation (outline-first) | Medium |
| Scene planner and coverage report | Medium |
| TTS per beat with timing | Easy to medium |
| Character system | Medium (one-time) |
| Asset library growth | Medium to hard (ongoing) |
| Renderer and per-scene cache | Medium |
| Captions, music, final mix | Easy (mostly reuse) |
| Review and re-render UI | Medium |
