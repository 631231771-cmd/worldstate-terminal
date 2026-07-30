# Open-source adoption audit

Reviewed: 2026-07-30

Scope: components that may reduce infrastructure work for the WorldState CPI
Event Lab. WorldState remains the owner of the event, point-in-time, surprise,
contamination, market-window, historical-match, and explanation domain models.

No upstream repository is forked. No third-party database or API schema becomes
part of the WorldState public contract.

## Decision summary

| Project | Reviewed commit | License | Decision |
| --- | --- | --- | --- |
| [OpenTerminalUI](https://github.com/Hitheshkaranth/OpenTerminalUI) | `fc16fd646405aec7a5525387be89c0cb376137c5` | MIT | Reference and independently rewrite small provider/OHLCV patterns |
| [Macrosynergy](https://github.com/macrosynergy/macrosynergy) | `d21d6ab0d83d1c597a5bd2355b8d66896a4a8bb6` | BSD-3-Clause | Optional Python dependency behind a WorldState adapter |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | `3e071fcc2cd9f891cac6040ae60296dba76dab46` | AGPL-3.0 | Keep optional and isolated; do not copy source into the core |
| [Fincept Terminal](https://github.com/Fincept-Corporation/FinceptTerminal) | `823f63848084f3869e4c9a487663f41f44d55989` | AGPL-3.0 or commercial license | Product research only; do not copy code, UI, or visual identity |

## OpenTerminalUI

### Candidate modules inspected

- `backend/adapters/provider_contracts.py`
  - asynchronous market-provider contract;
  - normalized OHLCV retrieval boundary.
- `backend/core/failover.py`
  - ordered provider waterfall;
  - failure count, cooldown, and health snapshot.
- `backend/services/provider_registry.py`
  - registry separated from provider implementations.
- `backend/db/ohlcv_cache.py`
  - hot/warm/cold cache tiers;
  - range coverage and missing-range reporting.
- `backend/providers/chart_data.py`
  - provider-specific symbol mapping and waterfall;
  - consistent OHLCV result objects.
- `frontend/src/shared/chart/FreshnessBadge.tsx` and
  `frontend/src/pages/DataQualityDashboard.tsx`
  - freshness and data-quality presentation patterns.

### Overlap with WorldState

WorldState already has an asynchronous provider protocol, SQLAlchemy
persistence, provider health, source provenance, and a TypeScript terminal. A
direct transplant would introduce a second SQLite layer, pandas, equity-centric
symbol assumptions, and React components into a non-React macro variant.

### Adoption decision

Use the concepts, not the implementation:

- define a WorldState-owned `MarketBarProvider` protocol;
- persist bars through the existing SQLAlchemy database;
- make provider attempts and data gaps first-class;
- support a deterministic CSV provider and an in-repository fixture provider;
- keep cache and WebSocket work outside the first CPI slice.

The implementation is independently written for event-window research. No
OpenTerminalUI source file is copied. If a later change copies a substantial
portion, the MIT notice must travel with that file and be recorded in
`THIRD_PARTY_NOTICES.md`.

Dependencies avoided: pandas, pyarrow, React, yfinance, and the upstream
standalone SQLite cache.

Maintenance risk: low for the WorldState-owned protocol; medium if a future
adapter follows upstream provider-specific behavior.

## Macrosynergy

### Candidate modules inspected

- `macrosynergy/panel/make_zn_scores.py`
- `macrosynergy/panel/historic_vol.py`
- `macrosynergy/panel/return_beta.py`
- `macrosynergy/visuals/correlation.py`
- `macrosynergy/signal/signal_return_relations.py`

The reviewed package version source identifies the development line as
`1.8.1`.

### Overlap with WorldState

WorldState already uses NumPy and Polars for small deterministic transforms.
Macrosynergy adds mature panel analysis but expects its own long-form
quantamental columns and brings pandas, scipy, statsmodels, scikit-learn,
matplotlib, seaborn, and pyarrow.

### Adoption decision

- expose a WorldState adapter that converts event-market observations into the
  Macrosynergy long-form input only inside the adapter;
- import Macrosynergy lazily;
- return WorldState-native dictionaries and domain records;
- keep the dependency optional so CSV/fixture event analysis works without it;
- use native NumPy calculations for the first CPI slice and allow the adapter
  to cross-check z-scores and historical volatility when installed.

No Macrosynergy internal type is stored in the database or returned by the API.

Maintenance risk: medium because the optional dependency has a broad numerical
stack. The adapter has a strict availability check and deterministic fallback.

Required notice: BSD-3-Clause copyright and disclaimer when distributed with
the optional dependency.

## OpenBB

### Candidate modules inspected

- `openbb_platform/core/openbb_core/provider/standard_models/futures_historical.py`
- `openbb_platform/core/openbb_core/provider/standard_models/consumer_price_index.py`
- provider implementations for yfinance, Cboe, FRED, and other data sources.

### Overlap with WorldState

WorldState already carries an optional pinned OpenBB dependency and has its own
provider protocol, FRED/ALFRED point-in-time model, and database. OpenBB's
standard models are useful as an external gateway but do not contain the
WorldState event bundle, consensus snapshots, contamination, or explanation
rules.

### Adoption decision

- do not copy OpenBB source;
- do not make OpenBB a required runtime dependency;
- retain a process/module boundary that can map OpenBB results into WorldState
  `MarketBar` records;
- defer activation until after CSV and fixture providers prove the CPI flow;
- ensure an OpenBB failure never blocks other providers.

AGPL-3.0 is a material distribution and network-use constraint. Any future
bundling or hosted deployment must receive a fresh license review.

Maintenance risk: medium to high because of provider extensions, a large
dependency graph, and licensing obligations.

## Fincept Terminal

### Areas reviewed

- market panels and configurable layouts;
- data-source mapping screens;
- chart and workspace organization;
- native desktop packaging and product navigation.

### Adoption decision

Fincept is research-only:

- no source copying;
- no UI component migration;
- no visual-identity imitation;
- no derived distribution;
- no dependency or runtime integration.

The repository is a native C++20/Qt application, is dual-licensed, and states
that business/internal-company use requires its commercial license. Its public
maintenance cadence also changed in June 2026. These factors make direct reuse
unnecessary and high risk for the CPI slice.

Maintenance and license risk: high.

## First-slice implementation boundary

The CPI Event Lab will therefore ship with:

1. WorldState-native event, event indicator, consensus snapshot, data-quality,
   market instrument, market bar, event-window, contamination, explanation,
   and historical-match models.
2. A provider protocol plus CSV and fixture providers independently rewritten
   around event windows.
3. An optional Macrosynergy adapter with no database or API leakage.
4. No copied OpenBB or Fincept source.
5. A WorldState-native event detail page using the existing frontend stack.

## Attribution control

Every imported dataset records source URL, capture time, manual/fixture/proxy
flags, verification state, granularity, latency, and quality grade. Code
adoption is tracked separately in `THIRD_PARTY_NOTICES.md`. Future changes must
add the exact upstream file, commit, license, and modification summary before a
substantial copy is merged.
