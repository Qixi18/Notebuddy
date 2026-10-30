# Knowledge tree growth implementation plan

> Implement inline using executing-plans and TDD; one independent review at delivery.

Goal: add course, notebook, Note and relation growth to home and forest while preserving the current completed rendering, geometry, interaction and navigation. Spec: the approved detailed plan in this conversation (2026-10-25).

Architecture: a shared session ledger distinguishes confirmed creation, authoritative baselines, pending growth and consumed IDs. Native SVG paint animations use the existing centerlines/materials; hit targets and geometry stay unchanged. No new runtime package, provider call, backend/API/schema change, commit or push.

## Tasks

- [x] 1. Capture the current working copy baseline: isolated fixture screenshots/geometry and existing frontend tests.
- [x] 2. RED/GREEN shared growth ledger: creation, directory/material/section/relationship observations, once-only playback and storage fallback.
- [x] 3. RED/GREEN native paint playback: masked trunk/limbs, petiole leaf unfold, completion/interruption/reduced motion and unchanged hit targets.
- [x] 4. Integrate home/forest and successful creation/upload/document saves; preserve page navigation, old snapshot compatibility and concurrency guards.
- [x] 5. Add new vine/new relation leaf playback, endpoint readiness, budgets and no replay on regroup/LOD.
- [x] 6. Full frontend tests/build, real-browser fixture and flow QA, independent review, fixes and handoff.

## Global constraints

- Same branch feat/home-knowledge-forest; retain all existing uncommitted work and user data.
- First scene return plays; home/forest share consumed events. First unrelated lazy load is static.
- Preserve existing empty-course decorative leaves and all current assets/geometry/LOD/layout.
- Animation only paints. Pointer/focus interaction completes affected playback before normal handlers.
- New elements require real returned IDs; failed uploads/saves never grow fake content.
- Visible and unoccluded scenes only; no camera/picker changes for animation. Finish on hidden/unmount.
- Max 3 tree sequences, 24 knowledge leaves, 2 vine stems; overflow displays normally, batch <=1500ms.
- Dynamic reduced motion immediately finishes effects; unsupported animation/storage remains usable.

## Review focus

Initial vs new lazy data; stale accepted responses; manual drafts/history restoration; StrictMode/remount; timers/effects/masks cleanup; relation grouping vs actual new IDs.

## Execution ledger

- Baseline HEAD 6866402; previous integration edits are part of the visual baseline, not to be reverted.
- Ruling: existing requested branch and approved direct execution supersede isolated-worktree/commit defaults.
- Ruling: native PowerShell plus project-local artifacts replace Unix-only skill bookkeeping scripts; this document tracks progress.
- Pre-flight: tasks 3–5 consume task 2's once-only ledger; all painting must remain optional, with identical static geometry. Existing forest snapshot knownNotebookIds is a compatibility input, not a second animation owner.
- Baseline: five screenshots and home geometry recorded before product edits. The original 50 Vitest files passed; the in-progress new ledger test correctly failed before its module existed. Vite realpath needed normal process permissions; initial sandbox EPERM was environmental.
- Ruling: old forest growth sets remain compatibility markers for existing snapshot/tests and the legacy renderer; CSS animations are suppressed in the managed canopy. The shared ledger alone owns new native playback.
- Ruling: temporary native masks use exact element bounds; sapling decorative foliage is animated as six groups, retaining the current artwork while avoiding dozens of independent effects and floating twigs.
- Review: one independent read-only review found premature offscreen vine consumption and overflow stems starting a second wave. Both reproduced, then fixed; regression also proves a pan can start deferred growth without a new data response.
- Extra regression: quota-only storage failure retains memory; restoring unseen material sections establishes a one-read baseline; dynamic reduced motion completes paint and preserves click navigation.
- Verification: final 38 Node +270 Vitest tests pass (308 total), production build passes, diff check passes. Static controlled original/new single-/three-leader and forest captures have zero differing pixels; initial unsettled screenshots were not used as final equivalence evidence.
- Browser: native branch/leaf masks observed during playback and removed afterward; real isolated API course creation retained its existing course-page navigation. Edge actual viewport checks: 390x844, 1024x768, 1440x900, no horizontal overflow. IAB viewport override was a no-op, so those checks were repeated in Edge.
- Performance: original and native-animation samples (three courses, two-to-three notebook update, six Notes/book) both recorded zero long tasks; 1900ms later active effects and temporary masks were zero. This is a local sample, not a universal device benchmark.
- Delivery: no commit, push or merge. See docs/handoffs/2026-10-25-tree-growth-animation.md; QA files/data are local-only.
- Final restoration audit: remember/restore also consumes unplayed child events, including material-generated Notes. Two regressions failed before the fix, then passed in the final full suite. Completed appearance and geometry were unaffected.
