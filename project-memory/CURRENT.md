# CURRENT — WorldState Macro Research Terminal

Updated: 2026-08-02

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
- Database head: `0004_analysis_reproducibility`
- API contract: `/v2`
- Product version: `0.4.0`

## Daily use

Use only these launcher layers:

- Desktop: `C:\Users\Administrator\Desktop\WorldState Terminal.bat`
- Repository: `WorldStateApp.bat`
- Maintenance: `WorldState.bat <command>`

Maintenance examples:

```powershell
.\WorldState.bat start
.\WorldState.bat status
.\WorldState.bat stop
```

Terminal: `http://127.0.0.1:4173/#today`

The duplicate Chinese BAT and obsolete PySide shortcut were hash-verified and
archived on 2026-07-31. No WorldState Start Menu, Startup, scheduled-task, or
residual port entry was present. Inventory and cleanup evidence are under
`docs/stabilization`.

## Implemented vertical slices

- CPI bundle: headline/core, MoM/YoY, revisions, composite classification.
- NFP bundle: payrolls, unemployment and wages, including revision effects.
- FOMC: statement, press conference, key Q&A and end stages with stage reversal.
- Cross-asset windows, earliest significant observed reaction and reversal.
- Fixed historical matching with 30/15/5 sample thresholds.
- Data quality, contamination, proxy and fixture labels.
- Deterministic explanations, EvidencePack and optional AI assistant.
- v0.4 true Z-score gating, NFP cross-unit revision safeguards and point-in-time cutoff metadata.
- Immutable AnalysisRun release/consensus/stage/OHLCV/history/config/output manifests with replay checks.
- AnalysisRun-linked Regime dimensions, contamination-aware matching and per-dimension contributions.
- Structured ResearchClaim → EvidenceItem bindings with deterministic fallback validation.
- `exchange-session-lite` calendar handling with explicit long-window experimental disclosure.
- Tauri product health verification, foreign-port refusal, child diagnostics and AI secret forwarding.

## Next work

1. Push the verified v0.4 stabilization commits and keep PR #8 Draft until all GitHub checks are green.
2. Import larger licensed point-in-time event/minute-bar history.
3. Add official BLS, BEA and Federal Reserve release providers.
4. Automate pre-T0 consensus snapshots from a legally usable source.
5. Package a frozen Python sidecar into a signed Windows installer.

## Non-negotiable boundaries

Do not reintroduce news/map breadth into the main workflow. Do not call
correlation unique causation. Do not hide proxy, fixture, manual, delayed,
contaminated or missing data. AI only summarizes an EvidencePack.
