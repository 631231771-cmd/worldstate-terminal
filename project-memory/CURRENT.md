---
project: World State Terminal
status: phase-8-global-macro-research-desk
updated: 2026-07-27
branch: feature/world-state-terminal
phase_1_formal_commit: a458e54d06b32992001693804b49f5f59a1f4019
phase_2_formal_commit: d144c96a6afcf674e854e80feefbfa66cdbf8549
phase_3_formal_commit: 3ca562b1264db05beb5bf94dfd819b419bee5263
phase_4_desktop_chain_commit: 1e9327e6f542a4224f3532b6452f8b4e094b2b84
phase_5_research_seminar_commit: 86b48c2397d5152d9e7d7304cfca9f40c73090d5
phase_6_clawfeed_webmcp_commit: 63b380e3b
phase_7_agent_reach_commit: c86554868
phase_8_research_desk_commit: ff6cd0be22232661bb9ed0d06bad29d48a447809
resume_from: phase-9-intraday-event-windows-and-research-journal
---

# Current continuation point

> [!important] Resume here
> Phase 8 is complete. World State Terminal is now a seven-workspace global
> macro research desk with an official event calendar, cross-asset system,
> country and topic lenses, transparent X research calls, reusable event
> playbooks, and an evidence-bounded AI tutor.
>
> Continue from intraday event-window measurement, actual-versus-consensus
> capture, or the persistent research journal. Preserve the core loop:
> **fact → expectation gap → pricing variable → financial conditions →
> economy → inflation/profits → policy response → asset confirmation**.

## What is running

- `WorldStateApp.bat` opens the terminal in a native PySide6 desktop window.
- `WorldState.bat` remains the operations launcher.
- Commands: `start`, `stop`, `restart`, `status`, `sync`, `doctor`, and `logs`.
- Launcher-managed services are running on ports `8000` and `4173`.
- The current browser preview is
  `http://127.0.0.1:4173/?lang=zh&view=overview`.

## Product structure

The terminal has seven URL-backed workspaces:

1. `overview` — 今日桌面：核心问题、市场状态、跨资产确认和今日主线。
2. `events` — 事件雷达：事实、预期差、完整传导、替代解释和反证。
3. `calendar` — 宏观日历：官方时间、双情景、首批定价变量和确认资产。
4. `markets` — 资产地图：十一类资产、1/5/20 日视角、历史与相关性。
5. `themes` — 国家与主题：八个主题和七个国家或地区研究入口。
6. `signals` — 观点与证据：研究管线、来源调用、相关性和证据边界。
7. `library` — 学习与复盘：六类事件模板、框架、课程和 AI 导师。

## Delivered state

- Eight prioritized world events and eleven tracked markets.
- Nineteen official upcoming macro events from BLS, BEA, Federal Reserve, ECB,
  Bank of Japan, and Bank of England.
- Every calendar event includes provenance, impact, a research question, two
  scenarios, first-pricing variables, and assets to watch.
- Market evidence includes 1-day, 5-day, and 20-day moves plus 30-day history.
- Four market regimes and seven explicit cross-asset relationships.
- Eight topic lenses, seven region lenses, and six reusable event archetypes.
- A seven-stage research pipeline keeps facts, news, viewpoints, official
  calendars, macro regimes, market confirmation, and AI explanation separate.
- Agent Reach reads twelve bounded X sources with three items per source.
- Live source ledger: twelve successful calls and thirty-six public items.
- External viewpoints carry a relevance score, label, reason, related event,
  mechanism lens, test variables, and caveat.
- Core explanations use a strict relevance threshold. Empty debate is allowed;
  unrelated debate is not.
- The AI tutor supports OpenAI Responses API, Ollama, compatible providers,
  and a deterministic no-key evidence mode.
- WebMCP exposes seven read-only tools for daily briefing, markets,
  viewpoints, call inspection, calendar, market system, and section navigation.
- Typography and responsive layout were rebuilt for comfortable reading.
- Cookie values stay only in the user's Agent Reach configuration and temporary
  child-process environment. They do not enter the API, frontend, database,
  logs, command arguments, Git, or this memory.

## Key files

- Desktop: `WorldStateApp.bat`, `scripts/worldstate_desktop.py`
- Operations: `WorldState.bat`, `scripts/worldstate.ps1`
- Official calendar:
  `services/macro-engine/src/macro_engine/providers/official_calendar.py`
- Public markets and news:
  `services/macro-engine/src/macro_engine/providers/public_intelligence.py`
- Agent Reach:
  `services/macro-engine/src/macro_engine/providers/agent_reach_x.py`
- Research system:
  `services/macro-engine/src/macro_engine/services/world_briefing.py`
- AI tutor: `services/macro-engine/src/macro_engine/services/ai_tutor.py`
- Frontend: `src/macro/MacroApp.ts`, `src/macro/macro-terminal.css`
- WebMCP: `src/macro/webmcp.ts`
- Client types: `src/services/macro-client.ts`
- Phase 8 research: `docs/macro/RESEARCH_DESK_2026-07.md`
- Operations contract: `docs/macro/OPERATIONS.md`
- Checkpoint:
  `00-checkpoints/2026-07-27-phase-8-global-research-desk.md`

## Verified

- Live briefing: eight events, eleven markets, and nineteen official events.
- July FOMC is present.
- Six of six official calendar source adapters are represented.
- Four regimes, seven correlations, eight topics, seven countries, six event
  archetypes, and seven research stages are returned.
- Twelve of twelve Agent Reach calls succeed; thirty-six items total; no call
  returns more than three items.
- Forty-three backend tests pass at 87.85% coverage.
- Ruff, mypy, TypeScript, Biome, Markdown lint, and direct Vite production
  build pass.
- All seven workspaces load in the browser with no application error and no
  horizontal overflow.
- Baseline body text is 16 px and zero moves render as `0.00%`, not signed
  negative or positive zero.

## Honest limitations

- Free prices are daily reference evidence, not exchange-grade live ticks.
- Official dates and scenarios are present, but consensus, actual, revision,
  surprise, and intraday reaction are not yet persisted.
- X posts are unverified viewpoints, never facts.
- Private institutional triggers, positioning, and order flow remain
  unknowable without licensed data.
- AI causal explanations remain hypotheses and are not investment advice.
- The native desktop window is not yet a signed standalone installer.

## Next priorities

1. Add intraday release and speech windows with daily fallback.
2. Persist consensus, actual, revision, surprise, and first market reaction.
3. Add a local pre-event hypothesis and post-event review journal.
4. Add user-manageable source pools and topic filters.
5. Package a signed desktop installer after the research workflow stabilizes.

## Guardrails

- Keep credentials backend-only and out of Vite variables, browser storage,
  Git, logs, and project memory.
- Never present a causal interpretation as an observed fact.
- Never claim knowledge of private fund positioning or order flow.
- Preserve citations, timestamps, provider state, and partial-failure behavior.
- Compute numerical market facts in code; use AI only for bounded explanation.
- `WorldState stop` must manage only verified PIDs owned by this checkout.
