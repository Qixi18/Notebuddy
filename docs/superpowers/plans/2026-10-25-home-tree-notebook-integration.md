# Home tree and notebook integration implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. User authorized direct execution on `feat/home-knowledge-forest`; keep changes local, with no push or merge.

**Goal:** Make existing tree leaves, editable notebook sections, reading positions and home refresh describe the same saved learning content.

**Architecture:** Preserve stable Note IDs and sources. Project legacy sections into the notebook document without overwriting existing prose; synchronize explicitly edited document sections transactionally with Note revisions and reversible removal. Reuse the existing reading-position API and refresh tree directories when returning to the application.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, React, Tiptap, pytest, Vitest.

**Spec:** Current chat: audit findings accepted for direct implementation; `agent.md` and `docs/backend-data-contract.md` govern identity, provenance, revisions and shared storage.

## Global Constraints

- Work in the user's existing `feat/home-knowledge-forest` branch.
- Preserve untracked documents, local credentials, uploads and business data.
- Keep existing Note IDs, source refs, tree slots, locks and immutable history.
- Use isolated test data; never reset the user's database.
- No visual redesign, cloud deployment, real provider calls, commit, push or merge.
- Explicit source anchors represent existing sections; new level-two headings represent user-authored knowledge sections. Inner imported headings stay below section level.

## Review Focus

- Same-named sections from different lectures/books retain independent identities and sources.
- A stale notebook save cannot overwrite a section updated by another editor.
- Removing/restoring a section must preserve its Note/history and must not revive intentionally hidden relations.
- Explicit leaf deep links take precedence over a saved reading position; async work must not leak across books.
- Failed or overlapping focus refreshes keep the previous usable tree and do not restore deleted courses.

### Task 1: Shared document/section lifecycle

Files: new `apps/backend/app/notes/notebook_sections.py`; update models, Alembic migration, notebook schemas/routes, outline and forest visibility; tests in `tests/test_notebook_tree_sync.py`.

- [x] RED: legacy sections appear as rich document content; saves update the same Note/title/revision; new headings receive stable IDs; removal is reversible; foreign anchors/stale revisions are rejected.
- [x] GREEN: implement projection and transactional synchronization, use durable relation jobs, preserve all provenance and slots.
- [x] Verify: `uv run pytest tests/test_notebook_tree_sync.py tests/test_notebook_document_v2.py tests/test_notebook_api.py -q`.

### Task 2: Reading and return state

Files: notebook API/types, `useNotebookSave`, `NotebookPage`, new reading hook, `HomeCourseGarden`; targeted notebook/home tests.

- [x] RED: save sends source revision metadata; branch reopen restores block/offset; explicit leaf wins; notebook selection survives home remount.
- [x] GREEN: persist block anchors through existing reading-position CAS API; retain local drafts and conflicting edits; persist home picker state scoped by course.
- [x] Verify targeted tests plus production build.

### Task 3: Refresh coherence

Files: `HomePage`, `ForestPage`, `useTreeDirectories`, home/forest tests.

- [x] RED: focus refresh updates loaded directory, counters and relations; failed refresh retains usable data; stale in-flight response cannot overwrite fresher state.
- [x] GREEN: refresh the existing watched course set, retaining request de-duplication and mounted guards.
- [x] Verify targeted refresh and navigation tests.

### Task 4: Delivery verification

- [x] Run backend Ruff/full pytest and frontend full tests/build; name any pre-existing failure (baseline single-course backup regression).
- [x] Run migration upgrade/idempotency and isolated HTTP/browser round trip: leaf → edit → save → tree preview → return/continue.
- [x] Request one independent review of the working diff, resolve material findings, and document evidence in `docs/handoffs/`.

## Execution ledger

- Baseline: HEAD `6866402`; tracked files clean. Frontend 279 passed/build passed; backend 272 passed/1 failed/1 skipped. Existing failure: `test_full_and_course_backup_keep_books_positions_and_slots_without_foreign_body`.
- Ruling: direct execution and existing branch were explicitly selected by the user; no additional approval checkpoint or worktree is needed.
- Pre-flight: Task 2 consumes Task 1's `section_revisions` metadata and optional Note `document_block_id`; reading position adds optional `block_id` without changing old chapter/note validation.

- Completion: all four tasks implemented and independently reviewed. Frontend 289 tests/build pass; backend Ruff passes, 285 tests pass with the same pre-existing backup failure and one external-fixture skip. Browser round trip used isolated data and no real providers.
- Compatibility: missing/partial source revision metadata cannot bypass conflicts; draft restore retains the original source baseline. Legacy source projection uses stable block IDs and refreshes stored source sections only when source timestamps are newer.
- Evidence and remaining scope: see docs/handoffs/2026-10-25-home-tree-notebook-integration.md. No commit, push or merge performed.
