---
project: World State Terminal
status: phase-10-complete
updated: 2026-07-28
branch: feature/world-state-terminal
implementation_commit: 93adf9169a97e3b021f1c7110dd3fdab97cad9a3
resume_from: phase-11-intraday-values-or-source-pools
---

# Phase 10 — append-only event research journal

## Outcome

The event workbench now preserves what the user thought before the outcome was
known. Each selected macro event has a structured, local journal with:

- central question;
- primary hypothesis;
- alternative explanation;
- expected transmission;
- disconfirming evidence;
- unresolved unknowns;
- Actual, Forecast, and Previous/Revision fields;
- post-event review;
- transferable lesson;
- current research status and next-check time.

## Product decisions

The journal is a learning and reasoning tool, not a trading P&L diary. The
design follows three principles:

1. Separate observations, hypotheses, alternatives, and unknowns.
2. Write falsifiers before the result is known.
3. Append every meaningful revision instead of rewriting the original view.

An unchanged save does not create a duplicate revision. A changed save records
the timestamp, changed fields, and full current snapshot.

## Storage and privacy

- Normal use stores notes in origin-scoped local browser storage.
- The native PySide6 app pins its profile to
  `.runtime/desktop-profile`.
- The desktop cache is isolated in `.runtime/desktop-cache`.
- Markdown export produces an Obsidian-readable event note.
- Journal text is not sent to Macro Engine, Agent Reach, X, AI providers, logs,
  Git, or project memory automatically.
- A `journalTest=1` URL uses tab-scoped session storage for isolated UI tests.

The existing server-side write boundary remains unchanged: Macro Engine exposes
no new browser-authenticated write route and no write token enters the browser.

## Verification

- Biome passes for the journal, app renderer, CSS, and focused test.
- TypeScript typecheck passes.
- Full macro production build and Vite secret guard pass.
- Desktop Python syntax check, Ruff, Qt, and WebEngine runtime checks pass.
- Markdown lint passes.
- Focused automated test proves:
  - first save creates one revision;
  - changing status and lesson creates a second revision;
  - unchanged save does not create a third revision;
  - Markdown contains the alternative explanation and falsification sections.
- Real browser interaction confirms the same three-step save behavior.
- At 430 px, the journal has no document-level horizontal overflow, keeps a
  16 px body baseline, and renders all eight text areas and both actions.
- Browser test data used session storage and disappeared when the test tab
  closed.

## Files

- `src/macro/research-journal.ts`
- `src/macro/MacroApp.ts`
- `src/macro/macro-terminal.css`
- `scripts/worldstate_desktop.py`
- `tests/macro-research-journal.test.mts`
- `docs/macro/RESEARCH_DESK_2026-07.md`
- `docs/macro/OPERATIONS.md`
- `docs/macro/SECURITY.md`

## Next priorities

1. Add timestamped intraday release and speech windows with daily fallback.
2. Persist verified consensus, actual, revision, surprise, and first reaction.
3. Add user-manageable source pools and topic filters.
4. Add a journal overview, search, comparison, and optional vault export.
5. Package a signed desktop installer after the research workflow stabilizes.

## Guardrails

- Never manufacture Actual, Forecast, Previous, or Revision values.
- Never convert a price reaction into proof of a private order or algorithm.
- Keep journal text local unless the user deliberately exports or shares it.
- Preserve old reasoning states; do not silently rewrite them.
- Keep the journal educational and evidence-oriented, not execution-oriented.
