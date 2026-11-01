# Curriculum Import Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement sequentially. Steps use checkbox syntax.

**Goal:** Complete a reliable preview-first curriculum import using the existing routes, durable jobs and storage.

**Architecture:** Reuse CurriculumImport, ForestJob JSON snapshots and ProcessingStep. Share page vision primitives with the LLM document route; keep Notebook bodies and document revisions untouched.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, SQLite, React, TypeScript, pytest, Vitest.

**Spec:** [design](../specs/2026-11-01-curriculum-import-design.md).

## Global constraints

- Remain on feat/overall-inspection at base 67677dd; preserve existing work and do not push without a new delivery request.
- No database schema migration or actual-user data repair; test only isolated databases and synthetic documents.
- Original source evidence is immutable; only confirmation may change course profiles or create courses.
- Freeze route/provider identity on creation, validate every model result, checkpoint successful bounded steps.
- Revert must be atomic, revision-guarded and preserve all later user data.

## Review focus

- Old import records and clients omit all new fields and route metadata.
- Worker yields, application restarts and user retries reuse valid steps without skipping source validation.
- Tables split across pages/chunks, repeated course names, ambiguous existing mappings and long names.
- Confirmation and revert races with other tabs, course renaming, uploaded notebooks and profile edits.
- Narrow screens can inspect all metadata, sources, warnings and confirmation/revert impact.

## Task 1: Correct retry state and expose progress

Files: backend forest/jobs.py, api/v1/forest_imports.py, schemas/forest_imports.py; frontend types.ts, CurriculumImportPanel.tsx; backend tests/test_curriculum_import.py and frontend forest-import.test.tsx.

- [x] Add regressions for failed → pending, repeated/confirmed retry rejection, continued polling and immutable evidence.
- [x] Implement atomic retry status transition, reset safe transient errors, expose current job progress.
- [x] Run focused tests before continuing.

## Task 2: Routes and resumable AI processing

Files: forest/curriculum.py; new curriculum_processing.py and curriculum_reading.py; document_processing/llm_reader.py; worker dispatch; API forms/types; processing tests.

Interfaces: route_snapshot(db, record) reads frozen route/provider JSON; read_page_image(client, png, number) returns validated ReadPage; extract_curriculum(db, record, client=None, max_new_steps=None) may raise WorkPending after successful steps.

- [x] Add failing tests for route defaults/overrides/frozen retries, no-provider admission, cache reuse, malformed model output and cooperative yields.
- [x] Share page vision call/validation without changing DocumentIR behavior; implement bounded curriculum read/extract checkpoints and model audit.
- [x] Integrate default/override control and actionable progress/error display.
- [x] Verify focused backend/frontend and existing LLM document regressions.

## Task 3: Course metadata, review and confirmation

Files: shared forest import schema, curriculum extraction/confirmation, frontend types and preview helpers/components, tests.

- [x] Cover code, credits, hours and required/elective fields; source validation; duplicate codes; exclusions/restores; profile revision conflict and no partial writes.
- [x] Extend local and AI extraction, preserve metadata in rows_json and map newly created IDs after confirmation.
- [x] Add review summary, metadata editing and comparison against confirmed import history.
- [x] Run focused contracts and confirmation tests.

## Task 4: Protected revert and delivery

Files: curriculum confirmation/revert service and endpoints, frontend confirmation actions, API/data docs and tests.

- [x] Prove revert restores exact prior profile attributes, soft-deletes only unused new courses, and refuses later user edits/content or repeated requests.
- [x] Store bounded confirmation snapshots in existing job JSON and apply revert with a checkpoint and atomic revision checks.
- [x] Add concrete impact confirmation and historic-record compatibility.
- [x] Official scripts/test.ps1 exit0 after review fixes; handoff updated; synthetic desktop/mobile visual QA passed. Keep current branch and uncommitted work for user-directed submission.
