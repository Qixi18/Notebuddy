# Natural trunk and course-stone implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make one-, two- and three-notebook trees grow naturally from a continuous trunk, and keep course stones visible with long names.

**Architecture:** Reuse the existing SVG canopy, note anchors and watercolor root assets. Author a common trunk with count-aware branch attachments; use the root asset's bark for both trunk and crown. Give course-title artwork its own bounded layer, independent of text height.

**Tech Stack:** React, TypeScript, SVG, CSS, Vitest, Vite.

**Spec:** User request in this chat, clarified to redesign the trunk and its one/two/three main branches as a whole.

## Global constraints

- Work in `feat/overall-inspection`; preserve backend/data contracts and all notebook/section identities.
- Preserve the existing watercolor style and root assets; use local SVG/CSS implementation as requested, without starting an OpenDesign generation.
- One notebook has a continuous leader; two have an asymmetric Y; three have a continuing central leader and staggered lateral forks.
- Both home and forest use the same trunk geometry. Expanded forest banks remain attached in world coordinates.
- Long titles retain their full accessible name and course-menu action; stones cannot collapse, disappear or cover adjacent controls.
- Use synthetic visual fixtures only. Do not inspect or migrate original user data.

## Review focus

- All three root variants with 1, 2 and 3 visible notebooks.
- Tangent and thickness continuity where a primary grows from the shared trunk.
- Dense forest banks after vertical scaling.
- Short, long Chinese and unbroken Latin titles at desktop and 390px widths.
- Existing note clicks, focus, growth animation and zero-notebook appearance.

## Task 1: Continuous trunk and count-aware branches

- [x] Add failing numeric/render regressions for a shared trunk, tangent continuity and scaled-bank attachment.
- [x] Add `trunkGeometry(variant, crownSize)` and attach primaries to it in `naturalBranchGeometry.ts`; retain the upper crown and exact leaf ownership.
- [x] Render the common trunk once in `CourseCanopy.tsx`; feather the existing roots and use rootstock bark consistently.
- [x] Run trunk, canopy, note-navigation and growth regressions.

## Task 2: Course-stone title layout

- [x] Reproduce short and long title layouts in an ignored synthetic browser fixture.
- [x] Keep artwork independent of title wrapping, with bounded responsive text and stable click targets.
- [x] Check desktop/mobile and forest captions; retain complete accessible names and course actions.

## Task 3: Verification and delivery

- [x] Run the complete Web test command and production build, plus `git diff --check`.
- [x] Inspect all nine trunk/crown combinations and long-title browser screenshots.
- [x] Review the final diff; leave changes on the requested branch for the user to inspect.

Verification and file list: [handoff](../../handoffs/2026-10-31-tree-trunk-and-stone.md). Final branch checks: 52 Node + 404 Vitest and 406 backend tests passed, with 4 optional backend tests skipped; Web and Desktop builds passed. See the [submission summary](../../handoffs/2026-11-01-overall-inspection-summary.md). Browser checks used synthetic data only.
