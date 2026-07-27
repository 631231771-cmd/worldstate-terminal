---
project: World State Terminal
phase: 5
date: 2026-07-27
implementation_commit: 86b48c2397d5152d9e7d7304cfca9f40c73090d5
status: complete
---

# Phase 5 — Daily research seminar and viewpoints

## Outcome

The desktop terminal now behaves like a daily macro research course instead of
another news dashboard. It turns the lead event into a graduate-style seminar,
keeps external opinions separate from facts, and supplies a free long-form
course path.

## Delivered

- A 75–90 minute daily seminar with four outputs:
  fact/unknown audit, time-lagged causal graph, cross-asset evidence table, and
  a falsifiable research memo.
- A six-module learning path based on free IMF, MIT OpenCourseWare, Open Yale,
  Federal Reserve, and QuantEcon material.
- Public perspective feeds from institutional, researcher, and practitioner
  sources with source-class labels and per-source diversity limits.
- Each viewpoint is translated into a mechanism lens, observable test
  variables, and a source-specific caveat.
- Optional official X recent-search integration using backend-only
  `MACRO_X_BEARER_TOKEN`.
- Explicit refusal to use, copy, store, or scrape browser cookies.
- AI tutor evidence now includes the complete chain, seminar, perspectives,
  cross-asset validation, and a bounded citation index.
- Larger readable seminar, viewpoint, and course typography with responsive
  two-column layouts and sticky-header-safe anchor navigation.
- Corrected Yahoo daily returns to use the prior trading session rather than
  the start of a one-month chart range.

## Validation

- 36 Macro Engine tests pass at 88.06% coverage.
- Ruff formatting and checks pass.
- TypeScript typecheck passes.
- Macro Vite production build passes.
- Native PySide6 desktop runtime check passes.
- Live public-source run: five events, eleven markets, six curated
  perspectives, one daily seminar, and six course modules.
- Browser check at 1280 × 720: 16 px body, 15 px viewpoint body, no horizontal
  overflow, working navigation anchors, and correctly rendered seminar,
  viewpoint, course, market, and AI tutor surfaces.

## Next best work

1. Add intraday event windows around scheduled releases and central-bank
   speeches, while keeping the existing daily fallback.
2. Add a local research journal so users can write and later score their
   pre-event hypotheses.
3. Add translation/summarization for English perspective source text when an
   AI provider is configured.
4. Configure X only if the user creates an official developer project and
   chooses a spending limit.
