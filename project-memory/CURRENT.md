---
project: World State Terminal
status: phase-3-world-explainer-complete
updated: 2026-07-23
branch: feature/world-state-terminal
phase_1_formal_commit: a458e54d06b32992001693804b49f5f59a1f4019
phase_2_formal_commit: d144c96a6afcf674e854e80feefbfa66cdbf8549
phase_3_formal_commit: 3ca562b1264db05beb5bf94dfd819b419bee5263
resume_from: phase-4-source-expansion-and-personal-learning-memory
---

# Current continuation point

> [!important] Resume here
> The evidence-grounded world explainer is complete at
> `3ca562b1264db05beb5bf94dfd819b419bee5263`. Start the next session from
> source expansion or personal learning memory; do not redo this product pivot.

## Delivered state

- `WorldState.bat` is the only user-facing launcher.
- Commands: `start`, `stop`, `restart`, `status`, `sync`, `doctor`, `logs`.
- A desktop shortcut named `打开世界状态终端.bat` starts the terminal.
- The default page is a Chinese-first daily world and market explainer.
- Free public feeds supply five ranked events with source links.
- Keyless daily market evidence covers gold, S&P 500, Nasdaq, dollar index,
  U.S. 10-year yield, WTI, Bitcoin, A shares, Hong Kong, Japan, and Korea.
- Event playbooks expose causal chains, affected assets, confidence, alternative
  explanations, and what evidence would confirm or reject the interpretation.
- Market explanations distinguish observed moves, interpretation, and unknown
  institutional order flow.
- The AI tutor supports OpenAI Responses API, Ollama, and compatible providers.
- With no AI key, a deterministic evidence tutor remains available.
- Phase 2 FRED/ALFRED macro states remain as the supporting data foundation.

## Key files

- Launcher: `WorldState.bat`, `scripts/worldstate.ps1`
- Public evidence:
  `services/macro-engine/src/macro_engine/providers/public_intelligence.py`
- World briefing:
  `services/macro-engine/src/macro_engine/services/world_briefing.py`
- AI tutor: `services/macro-engine/src/macro_engine/services/ai_tutor.py`
- API: `services/macro-engine/src/macro_engine/api/world.py`
- Frontend: `src/macro/`, `src/services/macro-client.ts`
- Product contract: `docs/macro/WORLD_EXPLAINER.md`
- Operations: `docs/macro/OPERATIONS.md`
- Progress: `docs/macro/progress/phase-03.md`

## Verified

- real keyless upstream run: 11/11 markets and 40 news items;
- real briefing: `LIVE`, five events, and eleven available markets;
- no-key tutor: deterministic, grounded, and five cited sources;
- 35 Macro Engine tests at 90.04% coverage;
- Ruff, strict mypy, TypeScript, Biome, safe-HTML, and security checks pass;
- macro production build passes;
- launcher restart/status, config migration, and HTTP readiness pass.

## Handoff state

- Phase 3 implementation is formally committed.
- Launcher-managed services are running on ports 8000 and 4173 for immediate
  review.
- Continue after reviewing
  `00-checkpoints/2026-07-23-phase-3-world-explainer.md`.

## Honest limitations

- free prices are daily reference evidence, not exchange-grade live ticks;
- free RSS can be delayed, removed, duplicated, or temporarily unavailable;
- the system cannot observe private fund triggers or prove institutional order
  flow without licensed data;
- the deterministic tutor is bounded and less flexible than a configured model;
- AI-generated causal explanations remain hypotheses, not investment advice;
- in-app browser visual automation was unavailable in this session.

## Guardrails

- Keep every credential backend-only and out of Vite variables, browser storage,
  Git, and logs.
- Never present a causal interpretation as an observed fact.
- Never claim knowledge of private fund positioning or order flow.
- Preserve citations, timestamps, provider state, and partial-failure behavior.
- Compute numerical market facts in code; use AI only for bounded explanation.
- `WorldState stop` must manage only verified PIDs owned by this checkout.
