---
project: World State Terminal
status: phase-9-wip
updated: 2026-07-27
branch: feature/world-state-terminal
base_commit: 7feae9db6
resume_from: finish-event-reaction-layout-and-verify
---

# Phase 9 WIP — event reaction research desk

> [!important] Exact continuation point
> The user liked the explanation path used for the live question about gold,
> silver, and crypto:
> **timeline → expectation gap → first pricing variables → asset-specific
> channels → leverage/microstructure → next verification**.
> Phase 9 is moving that path into the product. The data contract and main
> rendering code are in place, but the new UI still needs CSS, live service
> restart, browser review, tests, documentation, and a final commit.

## Product decision

Do not add another isolated top-level page. The calendar becomes an event
research workbench with two states:

1. Event preview before release.
2. Reaction review after release.

The overview gets a compact “刚刚发生” entry that opens the full workbench.
The full view separates observed facts from hypotheses and explicitly says
when actual, consensus, or precise minute-window data are not verified.

## Research completed with Agent Reach

Patterns adopted:

- TradingView: chronological scan, importance, Actual / Forecast / Prior,
  event-to-chart connection.
- Koyfin: interactive event detail, consensus/history, charts as the next
  layer instead of overloading the list.
- Econoday: raw values plus short economist commentary.
- `Sedryx/Private-Macro-Desk`: per-event price context and explicit warning
  that free schedules often omit actual results.
- `ankit637836/Macro-AI-Dashboard`: cross-market reaction cards around a
  selected event.
- `DocAMYMEI/CRATES`: event windows and asset-specific event-study thinking.

The chosen design is intentionally more educational than a trading calendar:
the six-step reasoning path is always visible, and “same direction” is not
treated as “same cause.”

## Changes already made

Backend:

- Added silver (`SI=F`) as the twelfth core market.
- Added silver’s dual role: precious metal plus industrial demand.
- Added gold/silver correlation to the cross-asset system.
- Added official U.S. Census durable-goods schedule rows, including the
  July 27, 2026 release, from the Census release schedule.
- Added a deterministic `event_reaction` contract:
  event state, value-verification state, six reasoning steps, pricing
  variables, asset-specific channels, amplifiers, verdict, caveats, and next
  checks.
- Kept the honest boundary that the official schedule does not provide a
  stable consensus/actual result feed.

Frontend:

- Added the `WorldEventReaction` client type.
- Changed the calendar heading to “事件研究工作台”.
- Added the latest event/reaction workbench renderer.
- Added a compact “刚刚发生” version to the overview.
- Default calendar selection now prefers the latest reaction event.
- Added released/upcoming states and a six-step path to each selected event.
- Calendar workspace now has a view-specific class so the styling can give
  the research path more width and move the AI tutor below it.

Tests:

- Added silver and event-reaction contract coverage.
- Added Census schedule coverage and updated the official-source count.
- Ruff passes.
- TypeScript typecheck passes.

## Modified files

- `services/macro-engine/src/macro_engine/providers/public_intelligence.py`
- `services/macro-engine/src/macro_engine/providers/official_calendar.py`
- `services/macro-engine/src/macro_engine/services/world_briefing.py`
- `services/macro-engine/tests/test_official_calendar.py`
- `services/macro-engine/tests/test_world_intelligence.py`
- `src/services/macro-client.ts`
- `src/macro/MacroApp.ts`

## Still unfinished

1. Add Phase 9 CSS for the six-step rail, verified-value strip, first-pricing
   variables, asset-channel rows, amplifiers, verdict, and responsive layout.
2. Make the calendar workspace full width and place the AI tutor below it.
3. Run the full backend tests, coverage, mypy, frontend format/lint, and Vite
   production build.
4. Restart services so the live API returns `event_reaction` and silver.
5. Inspect overview and calendar in the in-app browser at desktop and mobile
   widths; verify no overflow and readable fonts.
6. Update research/method docs and this durable memory.
7. Create a clean implementation commit, then a separate memory commit.

## Guardrails

- Never manufacture Actual / Forecast / Prior values.
- Label daily/latest price context as non-minute event evidence.
- Algorithms, stop-losses, options hedging, CTA flows, and crypto liquidations
  are amplifiers unless direct evidence proves more.
- Never claim knowledge of private fund orders from public prices.
- Keep the central learning loop visible before adding more content.

