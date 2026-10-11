# Course Notebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 实现用户确认的方案 A：每门课一本笔记本，每讲一个章节，正文与叶子跨讲独立，顺序阅读和准确定位。

**Architecture:** 课程构成笔记本，Material 构成章节，Note 构成小节。扩展已有表、版本和来源机制；课程概念与本讲正文分离。旧笔记保持身份与历史，多讲共享旧内容保留为历史整理。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic / SQLite；React / TypeScript / Vite。

**Spec:** `docs/superpowers/specs/2026-10-08-course-notebook-design.md`

## Global Constraints

- 本地单用户，API 仅监听 127.0.0.1；不测试真实用户库、不写入密钥。
- 不静默覆盖正文、修订、来源和旧入口；旧库迁移先检查点。
- 同名知识点跨讲复用概念，不复用正文；叶子 ID 为 Note ID。
- 分支 `feat/course-notebook`，用户已授权验证无问题后合并 main；本轮不推送 GitHub。
- 用户已委托符合要求即可推进，执行方式为本会话实施，最终独立审查。

## Review Focus

1. 两讲同名知识点 + 第 1 讲用户修改：第 2 讲不得复用或覆盖正文。
2. SQLite 原 Notes 唯一约束迁移：外键关联修订、建议、来源必须完整。
3. 旧笔记多讲/无来源：保留历史整理，不虚构讲次归属。
4. 章节重排遇到上传/移除/另一重排：版本冲突应返回 409。
5. 叶子定位、整本模式或同路由查询变化：不得选错小节或丢草稿。

### Task 1: Baseline and migration

**Files:** `app/db/models.py`, `app/db/migrate.py`, new `migrations/versions/*_course_notebook.py`, `tests/test_notebook_migration.py`; obsolete baseline tests only as evidenced.

**Interfaces:** Course.notebook_order_revision; Material.chapter_order; Note.material_id/section_key/section_order; KnowledgeNode.notes. Legacy Note ID/body/revisions remain.

- [x] Verify baseline Ruff, pytest and Web build; investigate failures and ledger exact causes.
- [x] Write `test_upgrade_preserves_single_and_shared_notes`: old head database contains single-source, shared-source and no-source notes; after migration IDs/body/revisions unchanged, only single-source material assigned; can insert second note for one concept; FK check empty; second startup unchanged.
- [x] Run the new test RED, implement SQLite constraint change and conservative backfill, run GREEN.
- [x] Test old unversioned database via existing migration regression; head expectations use Alembic head, not obsolete literal.
- [x] Run backend suite and Ruff; commit scoped migration changes.

### Task 2: Per-lecture generation

**Files:** `app/knowledge/extractor.py`, `app/knowledge/proposals.py`, `app/workers/material_worker.py`, `tests/test_notebook_generation.py`.

**Interfaces:** `ensure_note(..., material_id=None, section_key=None, section_order=0) -> Note`; explicit generation scope always material + stable page key, old helper calls retain legacy behavior.

- [x] Write `test_same_concept_has_independent_lecture_notes`: real parsed page fixtures generate two Note IDs for same concept, editing one preserves other; retry keeps IDs; changed generation creates suggestion.
- [x] Write `test_pending_similarity_keeps_readable_section`: similar candidate creates local note before review; reject/confirm preserve body.
- [x] Run RED; implement scoped lookup and generation, two-pass relations and material-specific web attachment; run GREEN.
- [x] Run generation/protection tests and backend suite; commit.

### Task 3: Notebook API and ordering

**Files:** new `app/notes/notebook.py`, `app/schemas/notebook.py`, `app/api/v1/notebook.py`, routes/schema exports; existing uploads/deletion/materials/notes/knowledge routes; `tests/test_notebook_api.py`.

**Interfaces:** `GET /courses/{id}/notebook`, `GET /courses/{id}/notebook/chapters/{material_id}`, `PATCH /courses/{id}/notebook/order` with `material_ids` and `expected_order_revision`; graph occurrences use note_id.

- [x] Write API tests: literal chapter and section order, exact note IDs, legacy/deleted groups, cross-course 404, invalid order 422, stale revision 409, upload/remove/restore invalidate ordering.
- [x] Run RED; implement outline and chapter endpoints, atomic course revision update, full-order validation and occurrence metadata; run GREEN.
- [x] Test course-only backup and restore after new fields; preserve sources and scope web sources by note material.
- [x] Run backend suite/Ruff; commit.

### Task 4: Course notebook reader

**Files:** new `src/pages/NotebookPage.tsx`, notebook API/types and reader helpers; modify NotesLibraryPage/App/routes/styles, existing note editor and detail where needed.

**Interfaces:** `/courses/:courseId/notebook?chapter=<materialId>&section=<noteId>`; old note detail redirects by ID; per-note save contract unchanged.

- [x] Before production UI, add runnable navigation tests for direct section, historical section, cross-chapter next/previous and unknown IDs; run RED.
- [x] Implement course bookshelf, outline, chapter/whole-book mode, sequential chapter loading, local sections and per-section Markdown editor/history/evidence.
- [x] Check unknown/deleted/loading/failed states, current URL after refresh and retained draft on conflicts.
- [x] Run frontend tests and build; commit.

### Task 5: Graph and source entry integration

**Files:** CourseKnowledgeStructure, MaterialsPage, AppLayout, routing/navigation helpers; frontend behavior tests.

**Interfaces:** all leaf/source entries target Note ID; query-only navigation is included in unsaved-draft guard; related occurrences list their lecture.

- [x] Add RED tests for same-concept different-lecture exact targets and query-only dirty navigation.
- [x] Implement per-lecture leaves, links to repeated/related occurrences and preserved legacy entry; route all source note_ids to notebook sections; run GREEN.
- [x] Verify browser course→chapter→whole book→edit→refresh→leaf and empty/error states; commit.

### Task 6: Acceptance, review and merge

**Files:** docs/api.md, architecture.md, acceptance.md, README.md, AGENTS.md, handoff/progress.

- [x] Run entire backend suite/Ruff, frontend tests/build and relevant isolated backup/migration flows; check each exit status.
- [x] Record synthetic/browser evidence separately from unavailable real-course/AI acceptance; update scope and API docs accurately.
- [x] Independent whole-branch reviewer compares spec, plan, tests and changed code; reproduce and fix material findings with RED→GREEN tests.
- [x] Commit verified changes; fast-forward merge to main only if feature and baseline checks pass; verify resulting Git state. No force push or unrelated staging. Code merge 1972aa3 passed backend/Web checks on main; handoff completion recorded on the task branch.

## Pre-flight/self-review

Tasks 2–5 consume Task 1 IDs and nullable history fields; Task 4–5 use Task 3 outline/occurrence contract. Source coverage remains note-to-source facts. New aliases do not duplicate stored bodies. All five Review Focus cases have explicit tests above. Commands run in their module directories. Whole-branch review remains required before the already-authorized local merge.
