---
project: World State Terminal
checkpoint: phase-3-world-explainer-complete
date: 2026-07-23
branch: feature/world-state-terminal
formal_commit: 3ca562b1264db05beb5bf94dfd819b419bee5263
resume_from: phase-4-source-expansion-and-personal-learning-memory
---

# Phase 3 world explainer complete

> [!success] Stable resume point
> The product has been rebuilt around daily world understanding and transparent
> cross-asset explanation. Do not restore the old score-dashboard-first home.

## Product decision

The terminal is for learning how events propagate through markets, not issuing
trading signals. Its default sequence is:

1. What happened?
2. Why does it matter?
3. Through which causal chain could it affect assets?
4. What moved in the observed daily market data?
5. What is interpretation, what is unknown, and what would falsify the view?
6. What follow-up question should the learner ask?

The Phase 2 macro-state engine remains the supporting foundation rather than
the primary homepage.

## Delivered

- Free, keyless RSS and official/public news aggregation with source links.
- Free daily Yahoo Finance evidence for eleven requested markets.
- Five ranked, diversified world events and Chinese event themes.
- Transparent event playbooks, causal chains, confidence, alternatives, and
  validation questions.
- Cross-asset explanations that explicitly avoid invented order-flow claims.
- Daily learning concept and transmission map.
- Provider-neutral AI tutor for OpenAI Responses API, Ollama, and generic
  OpenAI-compatible endpoints.
- Deterministic, cited, evidence-grounded answers when no AI key is configured.
- Chinese-first editorial frontend and sticky tutor.
- Five-minute cache, live/partial/offline states, safe feed parsing, bounded
  chat history, prompt-injection boundary, and backend-only credentials.
- Existing runtime configuration automatically gains the new AI settings.

## Verified

- Real free upstream evidence: 40 news items and 11/11 available markets.
- Real `/v1/world/briefing`: `LIVE`, five events, eleven markets.
- Real `/v1/world/ask`: deterministic provider, grounded result, five citations.
- Launcher restart/status, configuration migration, and both HTTP services.
- 35 engine tests at 90.04% coverage.
- Ruff, strict mypy, TypeScript, focused Biome, safe-HTML, and secret checks.
- Macro TypeScript/Vite/PWA production build.
- Documentation Markdown lint.

## Operating commands

From the repository root:

```bat
WorldState.bat start
WorldState.bat restart
WorldState.bat status
WorldState.bat logs
WorldState.bat stop
```

The desktop shortcut is:

```text
C:\Users\Administrator\Desktop\打开世界状态终端.bat
```

The page is available at:

```text
http://127.0.0.1:4173/?lang=zh
```

## Optional AI configuration

Edit ignored `.runtime/worldstate.env`. Choose one backend:

- `MACRO_AI_PROVIDER=openai` plus `OPENAI_API_KEY`;
- `MACRO_AI_PROVIDER=ollama` plus a local Ollama model;
- `MACRO_AI_PROVIDER=compatible` plus base URL, model, and optional compatible
  key;
- `MACRO_AI_PROVIDER=none` for the built-in deterministic tutor.

Never expose these keys through `VITE_*`, browser storage, committed files, or
logs.

## Next high-value work

- Add higher-quality official central-bank, statistics, and exchange sources.
- Add event-time intraday evidence when a legally usable free source exists.
- Persist user questions, concepts learned, and spaced-review prompts locally.
- Add source reliability scoring and cross-source corroboration.
- Add visual regression coverage once browser automation works locally.

## Known limits

- Prices are daily reference data, not tick-level or exchange-grade.
- Free feeds can be delayed or disappear.
- Private institutional keyword triggers and order flow are not observable.
- AI explanations are bounded hypotheses and educational material, not advice.
- In-app browser automation could not initialize in this environment.
