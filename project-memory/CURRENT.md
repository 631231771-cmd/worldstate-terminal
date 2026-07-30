# CURRENT — WorldState Macro Research Terminal

Updated: 2026-07-30

## Product truth

WorldState is a personal macro research and trading-assistance terminal. Its
daily job is to answer: what was released, how it differed from consensus, how
cross-assets reacted, what historical analogues show, and how confident an
evidence-bounded explanation should be.

World Monitor's news wall, world map and geopolitical-monitoring modules are no
longer part of the active architecture. Their final state is preserved at tag
`world-monitor-legacy-freeze` and branch `archive/world-monitor-legacy`.

## Active branch and milestones

- Working branch: `refactor/macro-research-terminal`
- Safety baseline: `f3e97fb0a`
- Core v3 implementation: `9f8fbac68`
- Database head: `0003_macro_research_terminal`
- API contract: `/v2`
- Product version: `0.3.0`

## Daily use

Double-click `WorldStateApp.bat`, or run:

```powershell
.\WorldState.bat start
.\WorldState.bat status
.\WorldState.bat stop
```

Terminal: `http://127.0.0.1:4173/#today`

## Implemented vertical slices

- CPI bundle: headline/core, MoM/YoY, revisions, composite classification.
- NFP bundle: payrolls, unemployment and wages, including revision effects.
- FOMC: statement, press conference, key Q&A and end stages with stage reversal.
- Cross-asset windows, earliest significant observed reaction and reversal.
- Fixed historical matching with 30/15/5 sample thresholds.
- Data quality, contamination, proxy and fixture labels.
- Deterministic explanations, EvidencePack and optional AI assistant.

## Next work

1. Import larger licensed point-in-time event/minute-bar history.
2. Add official BLS, BEA and Federal Reserve release providers.
3. Automate pre-T0 consensus snapshots from a legally usable source.
4. Package a frozen Python sidecar into a signed Windows installer.

## Non-negotiable boundaries

Do not reintroduce news/map breadth into the main workflow. Do not call
correlation unique causation. Do not hide proxy, fixture, manual, delayed,
contaminated or missing data. AI only summarizes an EvidencePack.
