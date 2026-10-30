# Dual Document Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Preserve standard processing and add resumable model-only document reading, note organization and relations, with a persistent route switch in Settings.

**Architecture:** Persist a route on source Assets, freeze it in parse/generation snapshots, and reuse the existing Document IR and Notebook write contract. Add page-render and multimodal reading adapters, a durable step cache, an AI planner and bounded relation traversal. The settings route is a default for new uploads only.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, httpx, pypdfium2, Windows Office / LibreOffice, React 19, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-dual-document-processing-design.md`

## Global Constraints

- Continue on user-selected `feat/document-processing` in the current checkout. Preserve unrelated `.runtime/` and `apps/web/output/`.
- Do not commit, push, merge, alter the real `.env`, or migrate the user's real database during verification.
- Default route `standard`; enum `standard|llm`; user Settings override applies to new uploads; existing tasks retain their route.
- New route defaults: 200 MiB, 2,000 pages, one page per vision call and at most two concurrent calls. No native text/OCR extraction in this route.
- Reuse the main model API, source IDs, Notebook revisions and existing forest representation; no silent offline fallback.

## Review Focus

- Settings changes while work is queued must not change its route or model identity.
- Reparse and duplicate requests must not reuse incompatible successful runs or append duplicate body content.
- Large Office/PDF files must not be rejected by the standard route's paragraph/page limits.
- A provider failure after successful pages/batches must retain valid progress without marking unread pages successful.
- Model output must not reference another file, course, Notebook or source block.

### Task 1: Settings and durable route contract

**Files:** `core/config.py`, `core/settings_store.py`, `schemas/settings.py`, `db/models.py`, new Alembic revision, `api/v1/config.py`; frontend `types`, `components/SettingsPanel.tsx`, `components/useSettingsDraft.ts`.

**Interfaces:** `resolve_route(value: str | None) -> str`, `route_limits(route: str) -> tuple[int,int]`; `Settings.document_processing_route`; `Asset.processing_route`, `Asset.processing_config_json`; `ProcessingStep` keyed by scope/stage/key/input fingerprint.

- [x] Add failing tests for persisted setting validation, default and active-task isolation; run pytest.
- [x] Add route settings/schema/migration and server capability response; add settings control with two options.
- [x] Verify settings tests and migration upgrade on isolated SQLite.

### Task 2: Upload selection and route propagation

**Files:** `services/uploads.py`, `services/image_assets.py`, `services/notebook_generation_inputs.py`, `api/v1/materials.py`, corresponding schemas and frontend upload APIs/components.

**Interfaces:** upload functions accept optional `processing_route`; resolve once, persist to Asset, reject mixed batches; responses expose route. Parser config snapshot comes from the Asset.

- [x] Add failing tests for larger AI uploads, image routes, duplicates, mixed batches and retained retry route.
- [x] Apply route-specific validation, streaming document uploads, configuration snapshots and explicit switch endpoint.
- [x] Verify upload/generation-input regressions and new tests.

### Task 3: Page rendering and model read pipeline

**Files:** new `document_processing/routes.py`, `checkpoints.py`, `rendering.py`, `llm_reader.py`, Office subprocess helper; `ai/deepseek.py`, `document_processing/service.py`, workers.

**Interfaces:** lazy `PageRenderer` yields page number/image; `read_document(db, run, asset, path, progress) -> DocumentIR`; cached validated steps survive failed runs; DeepSeek accepts multimodal content with bounded transient retries.

- [x] Add failing tests for local-parser bypass, empty/failed pages, JSON truncation and resume after mid-document failure.
- [x] Implement renderer and bounded Office conversion, page JSON validation, real evidence storage, step cache and progress/lease checks.
- [x] Verify synthetic PDFs/images, >500-page staged reading, Office conversion and provider request contracts.

### Task 4: AI plan and resumable note composition

**Files:** new `generation/llm_planner.py`; `generation/context.py`, `generation/composer.py`, `workers/notebook_generation_worker.py`, `api/v1/generation.py`.

**Interfaces:** `build_llm_plan(snapshot, cached_call) -> dict` uses existing units/batches contract; snapshot adds route/provider identity; composition checkpoints record validated nodes/source maps.

- [x] Add failing tests for model-selected hierarchy, source coverage and illegal IDs, cached composition retry and revision conflicts.
- [x] Build bounded hierarchical AI plans, preserve full input coverage, reuse composer and immutable source mapping, invalidate stale checkpoints.
- [x] Run generation and provenance tests.

### Task 5: Complete model-driven relation traversal

**Files:** `forest/relation_candidates.py`, `forest/notebook_relations.py`, new `forest/llm_relations.py`, relevant job serializers.

**Interfaces:** enqueue relation job with route from generation snapshot; LLM route traverses bounded groups of every current cross-course section, caches model summaries/decisions and validates endpoint fingerprints.

- [x] Add failing tests for >24 candidates, no keyword prefilter, empty results, hidden/manual relations and stale references.
- [x] Implement bounded traversal/resume and reuse existing persistence rules.
- [x] Run Notebook/forest relation suites.

### Task 6: User workflow and integration

**Files:** frontend settings, upload controls, progress/source components and shared API/types; `docs/parsing.md`, `docs/api.md`, `.env.example`, handoff record.

**Interfaces:** settings switch saves `NOTEBOOK_DOCUMENT_PROCESSING_ROUTE`; uploads freeze selected default; UI shows reading/organization/relationship progress and retry/switch actions.

- [x] Add meaningful UI tests for switch persistence, upload route and resumed state.
- [x] Complete controls/status display and route-specific capability/errors.
- [x] Run frontend tests/build and backend ruff/pytest, browser smoke test, small real-provider test with synthetic pages and isolated data.
- [x] Request one fresh whole-change review, fix important findings with reproductions, and record actual verification boundaries.

No commit steps: repository instructions require separate authorization for commits. Track execution and deviations in `.superpowers/sdd/2026-10-30-dual-document-processing/progress.md`.
