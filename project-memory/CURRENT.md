---
project: World State Terminal
status: phase-4-desktop-and-complete-chain
updated: 2026-07-27
branch: feature/world-state-terminal
phase_1_formal_commit: a458e54d06b32992001693804b49f5f59a1f4019
phase_2_formal_commit: d144c96a6afcf674e854e80feefbfa66cdbf8549
phase_3_formal_commit: 3ca562b1264db05beb5bf94dfd819b419bee5263
phase_3_ui_commit: 955382c6be45bb7902d46204f763893dae6e999e
phase_3_depth_commit: 6fb2760fc7b653b31b62597d559f6863d0a3c4b8
phase_4_desktop_chain_commit: 1e9327e6f542a4224f3532b6452f8b4e094b2b84
resume_from: phase-5-perspective-ingestion-and-event-windows
---

# Current continuation point

> [!important] Resume here
> The native desktop entry, readable typography, and complete eight-stage
> macro transmission loop are complete at
> `1e9327e6f542a4224f3532b6452f8b4e094b2b84`. Start the next session from
> curated perspective ingestion or intraday event windows. Preserve the
> fact → expectation → pricing → conditions → economy → inflation/profits →
> policy → assets loop.

## Delivered state

- `WorldStateApp.bat` opens the terminal as a native PySide6 desktop window.
- A real desktop shortcut named `世界状态终端.lnk` targets the native app.
- `WorldState.bat` remains the operations launcher.
- Commands: `start`, `stop`, `restart`, `status`, `sync`, `doctor`, `logs`.
- A desktop shortcut named `打开世界状态终端.bat` starts the terminal.
- The default page is a Chinese-first daily world and market explainer.
- The page uses one core question, a labeled causal chain, ranked event list,
  hypothesis-versus-market validation, market-role cards, retrieval practice,
  and a sticky AI tutor.
- The lead event now expands into a complete eight-stage macro loop with
  explicit time horizons, watch variables, a feedback loop, and falsifiers.
- The mechanism changes by event family: rates, energy, China growth, Asian
  rates/FX, geopolitical risk, trade policy, or a general fallback.
- Typography was raised across navigation, event analysis, market cards,
  validation, learning, and the AI tutor. The chain switches to two wide
  columns when four columns would become cramped.
- IMF, Bridgewater, and The Macro Compass are shown as distinct framework
  sources: official mechanism, system/cycle model, and practitioner hypothesis.
- Root scrolling was corrected so the AI tutor actually remains sticky.
- The legacy crawler copy is forcibly hidden in Macro mode, and the shared
  absolute-positioned app shell is reset so the page scrolls normally.
- Free public feeds supply five recency-aware, mechanism-deduplicated events
  with source links; low-signal central-bank administration is excluded.
- Keyless daily market evidence covers gold, S&P 500, Nasdaq, dollar index,
  U.S. 10-year yield, WTI, Bitcoin, A shares, Hong Kong, Japan, and Korea.
- Event playbooks expose expectation shifts, scenarios, expected market
  directions, labeled causal chains, confirmations, alternatives, and
  falsifiers.
- The leading scenario is checked against actual cross-asset directions and
  labeled as supported, weakened, mixed, or unclear.
- Market explanations distinguish observed moves, interpretation, and unknown
  institutional order flow.
- The AI tutor supports OpenAI Responses API, Ollama, and compatible providers.
- With no AI key, a deterministic evidence tutor remains available.
- Phase 2 FRED/ALFRED macro states remain as the supporting data foundation.

## Key files

- Desktop: `WorldStateApp.bat`, `scripts/worldstate_desktop.py`
- Operations launcher: `WorldState.bat`, `scripts/worldstate.ps1`
- Public evidence:
  `services/macro-engine/src/macro_engine/providers/public_intelligence.py`
- World briefing:
  `services/macro-engine/src/macro_engine/services/world_briefing.py`
- AI tutor: `services/macro-engine/src/macro_engine/services/ai_tutor.py`
- API: `services/macro-engine/src/macro_engine/api/world.py`
- Frontend: `src/macro/`, `src/services/macro-client.ts`
- Product contract: `docs/macro/WORLD_EXPLAINER.md`
- Operations: `docs/macro/OPERATIONS.md`
- Progress: `docs/macro/progress/phase-03.md`,
  `docs/macro/progress/phase-03-ui-redesign.md`,
  `docs/macro/progress/phase-03-content-depth.md`

## Verified

- real keyless upstream run: 11/11 markets and 40 news items;
- real briefing: `LIVE`, five events, and eleven available markets;
- no-key tutor: deterministic, grounded, and five cited sources;
- 35 Macro Engine tests pass at 91.00% coverage;
- Ruff, Python compilation, TypeScript, and macro Vite production build pass;
- native desktop runtime check passes and the PySide6 window remains responsive;
- desktop shortcut exists at `C:\Users\Administrator\Desktop\世界状态终端.lnk`;
- launcher restart/status, config migration, and HTTP readiness pass.
- real-browser inspection confirms eight chain stages, 16 px body text,
  14 px explanatory text, no horizontal overflow, and a sticky tutor;
- crawler content is hidden, page height is scrollable, and event expansion
  and answer reveal work in the browser.
- live recency-aware briefing returns today's energy event as the lead, eleven
  market rows, and a mixed cross-asset verdict.

## Handoff state

- Phase 4 desktop and complete-chain implementation is formally committed.
- Launcher-managed services are running on ports 8000 and 4173 for immediate
  review.
- Continue after reviewing
  `00-checkpoints/2026-07-23-phase-3-causal-learning.md`.

## Honest limitations

- free prices are daily reference evidence, not exchange-grade live ticks;
- free RSS can be delayed, removed, duplicated, or temporarily unavailable;
- the system cannot observe private fund triggers or prove institutional order
  flow without licensed data;
- the deterministic tutor is bounded and less flexible than a configured model;
- AI-generated causal explanations remain hypotheses, not investment advice;
- the desktop app is a native local window but not yet a signed standalone
  installer; first use still depends on Python and may install PySide6;

## Guardrails

- Keep every credential backend-only and out of Vite variables, browser storage,
  Git, and logs.
- Never present a causal interpretation as an observed fact.
- Never claim knowledge of private fund positioning or order flow.
- Preserve citations, timestamps, provider state, and partial-failure behavior.
- Compute numerical market facts in code; use AI only for bounded explanation.
- `WorldState stop` must manage only verified PIDs owned by this checkout.
