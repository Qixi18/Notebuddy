---
target: Simplify NoteBuddy course and note creation design
total_score: 23
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:D:\\工作台\\Notebuddy软件开发\\Notebuddy\\apps\\web\\src\\pages\\CourseLibraryPage.tsx"
target_fingerprint: "sha256:e201adb39ba37b0464c7d70f5efb9ed8a906c3b32343241a9d2f48537f589ef0"
target_path: "D:\\工作台\\Notebuddy软件开发\\Notebuddy\\apps\\web\\src\\pages\\CourseLibraryPage.tsx"
timestamp: 2026-10-21T14-31-11Z
slug: apps-web-src-pages-courselibrarypage-tsx
---
# NoteBuddy course-library creation design critique

## Design health score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 2 | Input and completed states appear simultaneously; success feedback is unspecified. |
| 2 | Match System / Real World | 3 | Course sections and note names are familiar; hierarchy is clear. |
| 3 | User Control and Freedom | 2 | Cancel, undo, and exit from inline entry are not shown. |
| 4 | Consistency and Standards | 2 | Course creation uses an anchored popover while note creation uses an inline row. |
| 5 | Error Prevention | 2 | Empty-name and validation states are not shown. |
| 6 | Recognition Rather Than Recall | 3 | The course heading makes the note destination visible in the right panel. |
| 7 | Flexibility and Efficiency | 3 | Name-only entry is fast, but duplicated note entry points can confuse. |
| 8 | Aesthetic and Minimalist Design | 3 | The restrained palette works; paired panels are sparse and dilute focus. |
| 9 | Error Recovery | 1 | Failure and recovery states are absent. |
| 10 | Help and Documentation | 2 | Labels are clear, but post-confirmation behavior is unspecified. |
| **Total** | | **23/40** | **Acceptable; meaningful refinement needed.** |

## Design specificity verdict

The proposal is grounded in NoteBuddy's course sections, notebook cards, search toolbar, and muted green palette. It is more product-specific than a generic form. However, it changes the current portrait illustrated note covers into wide book-icon cards, which exceeds the requested interaction simplification.

## Overall impression

The design is clean and calm, but not yet fully resolved. The biggest opportunity is to make the creation flow consistent and ensure each mockup depicts one real state at a time.

## What's working

- Search and creation controls sit above clearly separated course sections.
- Both flows ask only for a name, matching the user's low-friction goal.
- The green palette, whitespace, and simple controls fit the existing page's tone.

## Priority issues

1. **[P1] Unify the new-note entry point.** The top menu includes “新建笔记” while the course heading also has “＋ 新建笔记”. The course-level action clearly establishes the destination and supports name-only creation; define whether the top-level action remains and how it behaves.
2. **[P1] Separate input and completed states.** Each artboard shows an input form and the created result at once, making the interaction state ambiguous. Show the form state and post-confirmation state as separate views.
3. **[P2] Preserve the existing note-card design.** The mockup replaces the portrait illustrated covers with wide book-icon cards, suggesting an unrelated library redesign.
4. **[P2] Align post-confirmation behavior.** The proposal shows the new item inside the library, while current code navigates to the created course/notebook. The user's described outcome favors remaining in the course library and showing the new section/card.

## Persona red flags

- **Student capturing a quick idea:** duplicated entry points and unclear interaction states slow down a simple capture.
- **User with many courses:** the course-level action is clear, but a top-level note action needs an explicit destination.
- **Keyboard or screen-reader user:** cancel, success, and error states are not visible in the design proposal.

## Minor observations

The generated board is useful for comparing flows, but should be labeled as separate states. In the current live page, both creation actions still use centered dialogs; the note dialog also asks for a course. The detector returned zero generic findings. Browser injection and dynamic breakpoint checks were unavailable.

## Provocative question

Should new notes be created only from inside each course section, so their destination is automatic and the user enters only a name?
