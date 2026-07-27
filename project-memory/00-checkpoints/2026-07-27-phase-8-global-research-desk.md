---
project: World State Terminal
phase: 8
date: 2026-07-27
implementation_commit: ff6cd0be22232661bb9ed0d06bad29d48a447809
status: complete
---

# Phase 8 — Global macro research desk

## Product direction

World State Terminal is now organized as a daily macro research desk instead
of a news wall. Its job is to help the user move from an important event to the
expectation gap, transmission mechanism, cross-asset confirmation, competing
explanations, and a reviewable learning model.

The normal daily experience remains concise. Depth is available through
dedicated workspaces rather than by turning the product into a formal course or
an unbounded feed.

## Delivered

- Rebuilt the product into seven URL-backed workspaces:
  `overview`, `events`, `calendar`, `markets`, `themes`, `signals`, and
  `library`.
- Reframed the homepage as an operating desk with one lead question, four
  macro regimes, cross-asset confirmations and divergences, five prioritized
  events, topic focus, and the seven-stage research pipeline.
- Added an official macro calendar sourced from BLS, BEA, the Federal Reserve,
  ECB, Bank of Japan, and Bank of England. Every event includes provenance,
  importance, an event question, two scenarios, first-pricing variables, and
  the assets that should confirm or reject the interpretation.
- Added 1-day, 5-day, and 20-day market horizons plus 30-day price history for
  gold, S&P 500, Nasdaq, the dollar index, the U.S. 10-year yield, WTI,
  Bitcoin, A shares, Hong Kong, Japan, and Korea.
- Added four market regimes, seven cross-asset relationships, confirmation and
  divergence patterns, eight global topics, seven country or region lenses,
  and six reusable event archetypes.
- Expanded the Agent Reach research pool from six to twelve bounded X sources.
  It now covers major central banks, the IMF, BIS, OECD, U.S. Treasury, EIA,
  researchers, and market practitioners.
- Limited each X call to three items and kept a complete call ledger. The live
  pool is thirty-six items, while core explanations use a stricter relevance
  threshold so loosely related posts cannot masquerade as evidence.
- Added relevance scores, labels, reasons, related-event links, and
  word-boundary matching to external viewpoints.
- Expanded the AI tutor evidence pack with the official calendar, market
  system, topic map, countries, event archetypes, and the complete research
  pipeline. The no-key deterministic tutor can explain calendar and
  correlation questions.
- Expanded WebMCP to seven read-only page tools by adding calendar and market
  system access.
- Raised typography, removed decorative copy that did not teach anything, and
  added responsive layouts for the new calendar, regime, topic, country,
  correlation, pipeline, and event-template surfaces.
- Documented the mature product patterns used from Bloomberg, Macrobond,
  Koyfin, TradingView, MacroMicro, CRATES, Investment Macro Analyzer,
  MacroScope, and the existing World Monitor foundation. No third-party source
  code was copied.

## Live validation

- Evidence mode: `LIVE`.
- Eight prioritized events and eleven market rows.
- Nineteen upcoming official events, including the July FOMC decision.
- Six of six official calendar sources represented, with explicit official
  fallback status when a current-year page cannot be parsed.
- Four macro regimes, seven correlations, eight topics, seven regions, six
  event archetypes, and seven research-pipeline stages.
- Twelve of twelve Agent Reach X calls succeeded.
- Thirty-six X items returned, with at most three per source.
- Twelve ranked viewpoints; three cleared the broad relevance threshold and
  none were forced into the core brief without clearing the strict threshold.
- Forty-three backend tests pass at 87.85% coverage.
- Ruff, mypy, TypeScript, Biome, Markdown lint, and the direct Vite production
  build pass.
- Real-browser inspection confirms all seven workspaces, 16 px baseline text,
  correct `0.00%` formatting, no page errors, and no horizontal overflow.

## Honest limitations

- Free prices are daily reference evidence, not exchange-grade live ticks.
- The calendar currently knows official release times and scenarios, but it
  does not yet persist consensus, actual values, revisions, or intraday event
  windows.
- X posts remain unverified viewpoints. They are never treated as facts merely
  because the account is popular or official.
- The system cannot observe private fund triggers, positioning, or order flow
  without licensed data.
- Causal explanations are evidence-bounded hypotheses, not investment advice.

## Next best work

1. Add intraday windows around scheduled releases, central-bank decisions, and
   speeches, while retaining daily evidence as a fallback.
2. Persist consensus, actual, revision, surprise, and the first cross-asset
   reaction for every high-impact event.
3. Add a local research journal that records the pre-event hypothesis,
   confirming evidence, falsifier, and post-event review.
4. Add user-manageable source pools and topic filters without exposing Cookie
   values or allowing feeds to overwhelm the explanation.
5. Package the native desktop runtime into a signed standalone installer after
   the research workflow stabilizes.
