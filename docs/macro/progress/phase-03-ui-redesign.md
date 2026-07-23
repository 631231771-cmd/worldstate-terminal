# Phase 3 UI redesign

Status: complete on 2026-07-23.

## Why it was required

The first world-explainer interface was too dense and inherited layout rules
from the upstream World Monitor application. Its crawler-only content remained
visible, the app shell was absolutely positioned, horizontal overflow appeared,
and eleven market cards were compressed into an unreadable grid.

## Mature patterns reviewed

The redesign adopts patterns, not proprietary code:

- [Koyfin Market Dashboards](https://www.koyfin.com/features/market-dashboards/)
  for a one-screen cross-asset overview with progressive drill-down;
- [TradingView market widgets](https://www.tradingview.com/widget/) for a compact
  ticker that separates price, change, and deeper analysis;
- [Perplexity Finance](https://www.perplexity.ai/finance) for keeping cited
  follow-up questions beside the evidence being examined;
- [Bloomberg Terminal News](https://professional.bloomberg.com/products/bloomberg-terminal/news/)
  for a clear lead story and ranked news hierarchy.

## Delivered

- market ticker before editorial content;
- a restrained daily thesis card instead of an oversized full-width headline;
- a leading causal-chain card beside the thesis;
- compact, closed-by-default ranked event cards;
- larger typography and more readable market explanation cards;
- a sticky AI tutor on wide screens and a normal-flow tutor on narrow screens;
- clear section numbering and anchor navigation;
- responsive layouts for wide desktop, tablet, and phone;
- hard hiding of inherited crawler content in Macro mode;
- reset of inherited absolute app positioning and fixed-height overflow;
- no document-level horizontal scrolling.

## Verification

- TypeScript typecheck: pass;
- focused Biome check: pass;
- safe-HTML and local-secret checks: pass;
- Macro TypeScript/Vite/PWA production build: pass;
- real browser at 1,920 × 1,080: no horizontal overflow;
- real browser at 390 × 844: single-column responsive layout, no horizontal
  overflow;
- five event cards closed by default and first-card expansion verified;
- crawler copy hidden and full document scrolling verified.

## Commit

`955382c6be45bb7902d46204f763893dae6e999e`
