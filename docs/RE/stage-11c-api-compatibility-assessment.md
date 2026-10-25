# Stage 11C: API Compatibility Shim Assessment & Deprecation Plan

**Date**: 2026-10-25  
**Repository**: `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`  
**Branch**: `feat/animation-scaffold`  
**Status**: Assessment and Proposed Plan (Non-Destructive — No Code Changes)

---

## 1. Scope & Safety Statement

This assessment evaluates the residual API compatibility shims in the AI Video Clipper backend under `backend/app/api/v1/`. In accordance with Stage 11C mandatory rules:
- **Zero code removals or modifications** have been made to application source code, API routes, schemas, central composition, or OpenAPI definitions.
- The external reference repository (`C:\Lakshya\AI\autoshorts`) was strictly untouched.
- Pre-existing modifications and untracked files from earlier stages (Stages 4 through 11B) remain completely preserved.
- No changes were staged or committed to Git (`git diff --cached` remains empty).
- All findings are evidence-based, distinguishing verifiable in-repository facts from external consumer assumptions.

---

## 2. Preflight Repository State

- **Branch**: `feat/animation-scaffold`
- **Head State**: Working tree contains clean Stage 11B artifacts with 224 unit tests passing, zero architecture violations, and preserved shared infrastructure (`app.common`, `app.core`, `app.api.v1.api`, `app.api.v1.routes.health`, and common media shims).
- **Inspected Files**:
  - `backend/app/api/v1/schemas/candidates.py`
  - `backend/app/api/v1/schemas/jobs.py`
  - `backend/app/api/v1/schemas/projects.py`
  - `backend/app/api/v1/schemas/review.py`
  - `backend/app/api/v1/routes/review.py`
  - `backend/app/api/v1/api.py` (Central router aggregator)
  - `backend/app/main.py` (FastAPI application factory)
  - `backend/tests/unit/test_review_api.py` (Review API integration/unit test)
  - `backend/tests/unit/test_architecture_boundaries.py` (Architecture boundary enforcer)

---

## 3. Inventory of Remaining API Compatibility Shims

The five remaining compatibility files in `backend/app/api/v1/` are:

| File Path | Shim Type | Size | Implementation Pattern |
| :--- | :--- | :--- | :--- |
| `backend/app/api/v1/schemas/candidates.py` | Module Alias | 108 bytes | `sys.modules[__name__] = _impl` |
| `backend/app/api/v1/schemas/jobs.py` | Module Alias | 100 bytes | `sys.modules[__name__] = _impl` |
| `backend/app/api/v1/schemas/projects.py` | Module Alias | 104 bytes | `sys.modules[__name__] = _impl` |
| `backend/app/api/v1/schemas/review.py` | Module Alias | 102 bytes | `sys.modules[__name__] = _impl` |
| `backend/app/api/v1/routes/review.py` | Module Alias | 102 bytes | `sys.modules[__name__] = _impl` |

### Non-Shim Files Under `backend/app/api/v1/`
The following files under `backend/app/api/v1/` are **canonical shared infrastructure** and must be preserved permanently:
- `backend/app/api/v1/api.py`: The central API router aggregator composing routes across Clipper and Animation Studio.
- `backend/app/api/v1/routes/health.py`: The application-wide health check router.
- `backend/app/api/v1/schemas/common.py`: The authoritative standard error envelopes (`ErrorDetail`, `ErrorResponse`, `StatusResponse`, `PaginatedResponse`) required by TechSpec Section 11 and used by `app/main.py`.
- `backend/app/api/v1/schemas/health.py`: Health response models (`HealthResponse`, `SubsystemStatus`).

---

## 4. Canonical Targets & Current Callers

### A. Canonical Targets
Every shim delegates 100% of its module namespace to a canonical module inside `app.ai_clipper`:
1. `backend/app/api/v1/schemas/candidates.py` &rarr; `app.ai_clipper.api.schemas.candidates`
2. `backend/app/api/v1/schemas/jobs.py` &rarr; `app.ai_clipper.api.schemas.jobs`
3. `backend/app/api/v1/schemas/projects.py` &rarr; `app.ai_clipper.api.schemas.projects`
4. `backend/app/api/v1/schemas/review.py` &rarr; `app.ai_clipper.api.schemas.review`
5. `backend/app/api/v1/routes/review.py` &rarr; `app.ai_clipper.api.routes.review`

### B. Codebase Caller Scan Results
An exhaustive AST and regex scan across all production code, tests, documentation, and frontend scripts revealed:

| Target Shim | Active Production Dependencies | Test Dependencies | Documentation / Examples | Historical / Unresolved |
| :--- | :--- | :--- | :--- | :--- |
| `schemas/candidates.py` | None | `test_architecture_boundaries.py:511, 519` | None | None |
| `schemas/jobs.py` | None | None | None | None |
| `schemas/projects.py` | None | None | None | None |
| `schemas/review.py` | None | None | None | None |
| `routes/review.py` | None | `test_review_api.py:41` (monkeypatch) | `docs/ARCHITECTURE_REVIEW_AND_IMPLEMENTATION_PLAN.md:58` | None |

**Key Caller Findings**:
- **Zero Production Callers**: Not a single production module in `backend/app/` imports any of the 5 shims.
- **Central Composition Bypass**: `backend/app/api/v1/api.py` directly imports `from app.ai_clipper.api.routes import review as clipper_review`. It does *not* route through `backend/app/api/v1/routes/review.py`.
- **Sole Test Callers**:
  1. `test_architecture_boundaries.py` intentionally imports `app.api.v1.schemas.candidates` to assert that the legacy shim mechanism continues to preserve module identity and bidirectional monkeypatching.
  2. `test_review_api.py:41` uses `monkeypatch.setattr("app.api.v1.routes.review.OUTPUTS_BASE_DIR", fake_outputs)`.

---

## 5. Python Import Compatibility Analysis

All 5 shims employ the `sys.modules[__name__] = _impl` pattern. This produces the following behavioral guarantees for Python consumers:
1. **Module Identity**: `import app.api.v1.schemas.candidates as a` and `import app.ai_clipper.api.schemas.candidates as b` satisfy `a is b`.
2. **Symbol Identity**: All classes (e.g. `CandidateResponse`, `ReviewDetailResponse`), functions, and enums are physically identical instances in memory (`issubclass` and `isinstance` checks succeed across boundaries).
3. **Bidirectional Reflection**: Monkeypatching or modifying an attribute on the legacy module immediately modifies the canonical module, and vice versa.

### Impact of Python Shim Retirement
- If retired, any external Python script or third-party tool executing `from app.api.v1.schemas.candidates import ...` or `import app.api.v1.routes.review` would raise `ModuleNotFoundError`.
- Internal tests: `test_review_api.py:41` would require updating its monkeypatch string to `"app.ai_clipper.api.routes.review.OUTPUTS_BASE_DIR"`.

---

## 6. HTTP Route & OpenAPI Compatibility Analysis

A programmatic inspection of the running FastAPI application (`app.main:create_app()`) confirmed the following facts:

### A. Route Registration Hierarchy
- `backend/app/main.py` mounts `api_v1_router` from `backend/app/api/v1/api.py`.
- `backend/app/api/v1/api.py` explicitly mounts:
  - `health.router` (prefix `/health`)
  - `clipper_review.router` (prefix `/review` from `app.ai_clipper.api.routes.review`)
  - `animation_routes.router` (prefix `/animation` from `app.ai_animation.api.routes`)
- **Conclusion**: `backend/app/api/v1/routes/review.py` **does not participate in route registration**. The HTTP endpoints are registered exclusively by the canonical router.

### B. Registered Endpoints
The active HTTP review endpoints are:
- `GET /api/v1/review/caption-styles`
- `GET /api/v1/review/runs`
- `GET /api/v1/review/runs/{run_id}`
- `GET /api/v1/review/runs/{run_id}/media/{filename}`
- `GET /api/v1/review/runs/{run_id}/download/{filename}`

### C. OpenAPI Component Schemas
OpenAPI schema inspection confirmed that the generated schema components:
- `CaptionStyleResponse`, `RenderedClipInfo`, `ReviewCandidateItem`, `ReviewDetailResponse`, `ReviewRunSummary` are generated directly from type hints on `app.ai_clipper.api.routes.review` handlers, resolving to `app.ai_clipper.api.schemas.review`.
- Shared domain types (`EditorialGoal`, `ScoreBreakdown`, `ValidationStatus`) resolve to `app.ai_clipper.domain.candidates.models`.

### D. HTTP Compatibility Conclusion
The HTTP API routes, request validation, response serialization, URLs, JSON payloads, and `/openapi.json` specifications are **100% independent** of the five compatibility shims. Retiring or retaining these files has **zero impact** on HTTP clients, browsers, or frontend applications.

---

## 7. External Consumer Risk Assessment

While the repository contains no internal production callers, we must formally address external consumer risk:

| Consumer Type | Likelihood | Impact if Removed | Mitigation / Alternative |
| :--- | :--- | :--- | :--- |
| **HTTP Clients (Frontend, Postman, curl)** | High | **Zero**. HTTP URLs and contracts are unaffected. | None required. |
| **Downstream Python Library** | Low | High (`ModuleNotFoundError`). AI Video Clipper is an application, not a published PyPI library. | Provide transitional deprecation warning or canonical import mapping. |
| **Developer Maintenance Scripts** | Medium | Medium. A standalone maintenance script might import `app.api.v1.schemas.*`. | Keep shims through a grace period; update script paths. |
| **Subprocess / Test Harnesses** | Low | Low. Standard test suite is already canonicalized. | Update line 41 of `test_review_api.py`. |

---

## 8. Per-File Recommendations & Rationale

| Shim File | Recommendation | Rationale |
| :--- | :--- | :--- |
| `backend/app/api/v1/schemas/candidates.py` | **Deprecate & Schedule for Retirement** | Zero production callers; tested by `test_architecture_boundaries.py`. Safe to retire once authorized. |
| `backend/app/api/v1/schemas/jobs.py` | **Deprecate & Schedule for Retirement** | Zero internal callers anywhere in the repository. Safe to retire once authorized. |
| `backend/app/api/v1/schemas/projects.py` | **Deprecate & Schedule for Retirement** | Zero internal callers anywhere in the repository. Safe to retire once authorized. |
| `backend/app/api/v1/schemas/review.py` | **Deprecate & Schedule for Retirement** | Zero internal callers; canonical schemas used everywhere. Safe to retire once authorized. |
| `backend/app/api/v1/routes/review.py` | **Deprecate & Schedule for Retirement** | Central router directly imports canonical router. Only 1 test monkeypatch (`test_review_api.py:41`) needs alignment. |

**Summary Recommendation**:  
All 5 files are redundant shims that can be safely retired in a future, explicitly authorized cleanup stage (Stage 12), with zero impact on HTTP runtime or API contracts.

---

## 9. Proposed Deprecation Window & Migration Plan (Proposal Requiring Approval)

> [!IMPORTANT]
> This migration plan is a formal proposal. In accordance with Stage 11C instructions, no shims are deleted or deprecated in code during this stage. Implementation requires explicit user authorization.

### Proposed Phase 1: Pre-Retirement Alignment (Stage 12A)
1. **Align `test_review_api.py:41`**:
   Change:
   ```python
   monkeypatch.setattr("app.api.v1.routes.review.OUTPUTS_BASE_DIR", fake_outputs)
   ```
   to canonical:
   ```python
   monkeypatch.setattr("app.ai_clipper.api.routes.review.OUTPUTS_BASE_DIR", fake_outputs)
   ```
2. **Update Architecture Boundary Enforcer**:
   Retire the `legacy_schema` identity and monkeypatch assertions in `backend/tests/unit/test_architecture_boundaries.py`, while maintaining strict import boundaries preventing any new imports of `app.api.v1.schemas.{candidates,jobs,projects,review}` or `app.api.v1.routes.review` from production code.

### Proposed Phase 2: Shim Removal (Stage 12B)
1. Delete the 4 schema shims under `backend/app/api/v1/schemas/`:
   - `candidates.py`
   - `jobs.py`
   - `projects.py`
   - `review.py`
2. Delete the 1 route shim:
   - `backend/app/api/v1/routes/review.py`
3. Preserve the canonical shared files:
   - `backend/app/api/v1/schemas/common.py`
   - `backend/app/api/v1/schemas/health.py`
   - `backend/app/api/v1/routes/health.py`
   - `backend/app/api/v1/api.py`

### Proposed Phase 3: Verification (Stage 12C)
1. Verify `pytest backend/tests/unit -v` (224 tests passing).
2. Verify `pytest backend/tests/unit/test_review_api.py -v`.
3. Verify `pytest backend/tests/unit/test_architecture_boundaries.py -v`.
4. Inspect OpenAPI generation to ensure identical `/openapi.json` output.

---

## 10. Stale Documentation-Reference Inventory

During Stages 11A, 11B, and 11C, several stale references to retired CLI, domain, services, and API paths were identified across the repository. They are cataloged below by category:

### A. User-Facing Documentation & Runbooks (Informational)
- `docs/RUNBOOK.md`: References to `python -m app.cli.process_local` and `python -m app.cli.render_clips`.
- `docs/STARTUP.md`: References to legacy CLI execution commands.
- `README.md`: Historical CLI entry point snippets.
- `docs/ARCHITECTURE_REVIEW_AND_IMPLEMENTATION_PLAN.md:36-58, 272-285`: Mermaid diagrams and architectural notes referencing `app.services.*`, `app.domain.*`, and `app.api.v1.routes.review`.
- `docs/STAGE4_ORCHESTRATION_IMPLEMENTATION_PLAN.md:28-32`: Stage 1–3 pipeline table referencing `app.services.*` and `app.domain.*`.

### B. Code Docstrings & UI Help Text
- `backend/app/ai_clipper/cli/process_local.py:15`: Module docstring example containing `python -m app.cli.process_local`.
- `frontend/ai-clipper-ui/src/features/candidates/ReviewView.tsx:327`: Static UI copy rendering `python -m app.cli.render_clips --run-dir ...` in an informational help block.

### C. Logger Channels (Intentionally Preserved)
These strings are logging category identifiers, not Python module imports. As established in Stage 11B, they are intentionally preserved:
- `backend/app/ai_clipper/cli/discover_candidates.py:27`: `logging.getLogger("app.cli.discover_candidates")`
- `backend/app/ai_clipper/cli/orchestrate.py:24`: `logging.getLogger("app.cli.orchestrate")`
- `backend/app/ai_clipper/cli/process_local.py:21`: `logging.getLogger("app.cli.process_local")`
- `backend/app/ai_clipper/cli/process_short_clips.py:21`: `logging.getLogger("app.cli.process_short_clips")`
- `backend/app/ai_clipper/cli/render_clips.py:20`: `logging.getLogger("app.cli.render_clips")`
- `backend/app/ai_clipper/services/candidates/ranking.py:18`: `logging.getLogger("app.services.candidates.ranking")`
- `backend/tests/unit/test_candidate_ranking.py:379`: `caplog.at_level(..., logger="app.services.candidates.ranking")`

### D. Intentional Architecture Boundary Test Fixtures
- `backend/tests/unit/test_architecture_boundaries.py`: Lines 307, 317, 443, 470 contain inline test strings (`"import app.services.pipeline.orchestrator"`, etc.) used to verify that the boundary checker successfully intercepts prohibited legacy imports.

**Recommendation**: Perform a single, dedicated documentation and UI consistency cleanup pass prior to final delivery, updating docstrings and runbooks to canonical paths without modifying production behavior.

---

## 11. Recommended Stage 12 Verification Checklist

When user authorization to execute Stage 12 is granted, use this checklist:
- [ ] Align monkeypatch in `backend/tests/unit/test_review_api.py:41` to canonical path.
- [ ] Remove `backend/app/api/v1/schemas/candidates.py`.
- [ ] Remove `backend/app/api/v1/schemas/jobs.py`.
- [ ] Remove `backend/app/api/v1/schemas/projects.py`.
- [ ] Remove `backend/app/api/v1/schemas/review.py`.
- [ ] Remove `backend/app/api/v1/routes/review.py`.
- [ ] Update `backend/tests/unit/test_architecture_boundaries.py` to retire legacy schema assertions while preserving boundary rules.
- [ ] Confirm `backend/app/api/v1/schemas/common.py` and `health.py` remain untouched.
- [ ] Confirm `backend/app/api/v1/routes/health.py` and `api.py` remain untouched.
- [ ] Run architecture boundary checker: `pytest backend/tests/unit/test_architecture_boundaries.py -v`.
- [ ] Run full backend unit suite: `pytest backend/tests/unit -v` (expect 224 passed).
- [ ] Verify OpenAPI schema equivalence: `python scratch/inspect_openapi.py`.
- [ ] Verify zero remaining imports of retired paths.
- [ ] Verify Git status confirms zero staged files and clean working tree.

---

## 12. Explicit File Audit

### Files Inspected During Stage 11C
- `backend/app/api/v1/schemas/candidates.py`
- `backend/app/api/v1/schemas/jobs.py`
- `backend/app/api/v1/schemas/projects.py`
- `backend/app/api/v1/schemas/review.py`
- `backend/app/api/v1/routes/review.py`
- `backend/app/api/v1/routes/health.py`
- `backend/app/api/v1/schemas/common.py`
- `backend/app/api/v1/schemas/health.py`
- `backend/app/api/v1/api.py`
- `backend/app/main.py`
- `backend/app/ai_clipper/api/routes/review.py`
- `backend/app/ai_clipper/api/schemas/candidates.py`
- `backend/app/ai_clipper/api/schemas/jobs.py`
- `backend/app/ai_clipper/api/schemas/projects.py`
- `backend/app/ai_clipper/api/schemas/review.py`
- `backend/tests/unit/test_review_api.py`
- `backend/tests/unit/test_architecture_boundaries.py`

### Files Changed During Stage 11C
- `docs/RE/stage-11c-api-compatibility-assessment.md` (Created new assessment deliverable)
- **Zero other files modified, created, or deleted**.
