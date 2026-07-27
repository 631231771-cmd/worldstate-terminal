---
project: World State Terminal
phase: 6
date: 2026-07-27
implementation_commit: 63b380e3b
status: complete
---

# Phase 6 — Deep brief, ClawFeed, and WebMCP

## Corrected product direction

“像课题一样研究” means the explanation should have research-level depth, not
that the user should perform a 75–90 minute seminar, submit work, or follow a
course schedule. The daily surface is now designed to be consumed directly.

## Delivered

- Replaced the daily seminar contract and UI with an approximately eight-minute
  five-part deep brief:
  fact and expectation gap, transmission mechanism, cross-asset evidence,
  competing explanations, and the next observations/falsifiers.
- Removed assignment, deliverable, duration, and seminar UI/code paths.
- Kept free courses as a collapsed optional reference for concept lookup.
- Applied ClawFeed's fixed-edition principle by default: a growing source pool
  does not expand the homepage indefinitely.
- Added an optional backend adapter for a separately running ClawFeed instance.
  It reads at most three public daily digests, strips markup, truncates text,
  and never requires browser cookies.
- Added three progressive WebMCP page tools through
  `navigator.modelContext.provideContext`: read the daily brief, explain one
  market, and show a visible terminal section.
- Documented upstream revisions, licenses, configuration, security boundaries,
  and the reason ClawFeed is not bundled as a second desktop service.
- Increased and verified readable typography for the learning surface.

## Validation

- 37 Macro Engine tests pass at 88.10% coverage.
- Ruff format/check and TypeScript typecheck pass.
- Macro Vite production build passes.
- Live desktop services return `LIVE`, five events, eleven markets, six
  perspectives, five deep-brief sections, three declared WebMCP tools, and no
  legacy seminar field.
- Browser inspection confirms five deep cards, Chinese lead summary, collapsed
  course references, 16 px deep body, 14 px event/market explanations, exact
  sticky-header anchor placement, and zero horizontal overflow.
- The current in-app browser reports WebMCP unsupported and correctly keeps the
  full ordinary UI.

## Integration boundaries

- ClawFeed reviewed at `38b43f0c3d5c781acbc3173a3a4a47f480cb18a5`
  under MIT.
- WebMCP reviewed at `971aa24aea2afd865ca8607ba79a486fc7429360`
  under the W3C Software and Document License.
- No upstream source files are vendored.
- External ClawFeed content remains an untrusted summary, not a verified fact.
- WebMCP tools are local/read-only and expose no secrets, cookies, or trading
  actions.

## Next best work

1. Add intraday event windows around scheduled data releases and central-bank
   speeches, with the current daily prices as fallback.
2. Add a local research journal only if it reduces repeated thinking; do not
   turn it into mandatory homework.
3. Add AI-assisted Chinese translation/summarization of English source text
   when a user-configured provider is available.
