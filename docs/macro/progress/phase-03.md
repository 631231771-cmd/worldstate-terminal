# Phase 3 progress

Status: complete on 2026-07-23.

## Product pivot

The macro-score dashboard is now the supporting data layer. The default terminal
experience is a Chinese-first daily explanation of the world and financial
markets.

## Delivered

- five ranked global events from free public and official feeds;
- eleven keyless daily markets: gold, S&P 500, Nasdaq, U.S. dollar index,
  U.S. 10-year yield, WTI, Bitcoin, Shanghai Composite, Hang Seng, Nikkei 225,
  and KOSPI;
- transparent event playbooks, causal chains, affected assets, confidence, and
  source links;
- cross-asset market explanations that never invent institutional order flow;
- a daily learning concept and evidence-validation question;
- provider-neutral tutor routing for OpenAI Responses API, Ollama, and generic
  OpenAI-compatible services;
- deterministic evidence tutor when no AI key exists;
- prompt-injection boundary, bounded history, backend-only secrets, source
  citations, and educational disclaimer;
- five-minute public evidence cache with explicit live/partial/offline status;
- news-first editorial interface with market pulse, event deep dives,
  transmission map, daily lesson, macro foundation, and AI tutor;
- updated Windows runtime configuration, API, operations, limitations, and
  product-direction documentation.

## Verification

- real keyless upstream run: 11/11 markets and 40 news items;
- real `/v1/world/briefing`: `LIVE`, five events, eleven markets;
- real `/v1/world/ask` without AI key: deterministic, grounded, five citations;
- Macro Engine: 35 tests passed at 90.04% coverage;
- Ruff and strict mypy: pass;
- root TypeScript and focused Biome checks: pass;
- Macro production build: pass;
- launcher restart/status and HTTP readiness: pass;
- in-app visual automation remained unavailable because the local browser
  connection could not initialize.

## Commit

`3ca562b1264db05beb5bf94dfd819b419bee5263`
