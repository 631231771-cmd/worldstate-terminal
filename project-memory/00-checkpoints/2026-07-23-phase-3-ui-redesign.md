---
project: World State Terminal
checkpoint: phase-3-ui-redesign-complete
date: 2026-07-23
branch: feature/world-state-terminal
formal_commit: 955382c6be45bb7902d46204f763893dae6e999e
resume_from: phase-4-source-expansion-and-personal-learning-memory
---

# Phase 3 UI redesign complete

> [!success] Stable resume point
> The world explainer now has a verified responsive workspace. Preserve this
> information hierarchy and do not restore the original compressed market grid.

## Root cause fixed

The shared `index.html` contains crawler-visible World Monitor copy and the
shared application shell uses absolute positioning with a viewport-height
container. The Macro variant did not reliably receive the early `js` class, so
the crawler content appeared behind the app. The app also inherited fixed-height
overflow, which prevented normal document scrolling.

Macro startup now hides the crawler elements directly and adds a dedicated
document class. Macro CSS resets the shared app shell to normal document flow,
auto height, and responsive width.

## Current layout

1. Sticky product header and section navigation
2. Horizontally scrollable eleven-market ticker
3. Daily thesis with evidence counts
4. Leading causal transmission chain
5. Ranked, collapsed event list
6. Market explanation cards
7. Transmission and daily-learning cards
8. Macro foundation
9. Evidence-grounded AI tutor

The tutor remains sticky on wide screens and moves below the editorial column
on smaller screens.

## Browser verification

- Default viewport: crawler copy hidden, document width equals viewport width.
- 1,920 × 1,080: three-part lead workspace and sticky tutor render correctly.
- 390 × 844: one-column layout, scrollable market ticker, no horizontal page
  overflow.
- Document height expands beyond the viewport and scrolls normally.
- All five event cards start closed; event expansion works.

## Quality verification

- TypeScript, Biome, and safe-HTML checks pass.
- Vite environment and local secret checks pass.
- Macro production build passes with 2,362 transformed modules.
- Existing large-chunk warnings remain inherited from the upstream application.

## Primary files

- `src/macro/MacroApp.ts`
- `src/macro/macro-terminal.css`
- `docs/macro/progress/phase-03-ui-redesign.md`

## Next work

Prioritize source quality, event de-duplication, Chinese summaries, intraday
evidence, and local learning memory. Visual work should be incremental and
validated in the browser at desktop and phone breakpoints.
