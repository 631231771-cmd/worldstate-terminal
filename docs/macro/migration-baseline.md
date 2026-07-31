# WorldState Macro Research Terminal migration baseline

Captured on 2026-07-30 (Asia/Shanghai) from Git commit
`a142d4ea9efed935316715bab1f548fbb7d33d4c`.

This document is the recovery and equivalence baseline for the migration away
from the World Monitor product model. It records what existed before database
v3, API v2, the five-workspace terminal UI, and the Tauri desktop shell replaced
the old system.

## Recovery points

- Annotated tag: `world-monitor-legacy-freeze`
- Archive branch: `archive/world-monitor-legacy`
- Migration branch: `refactor/macro-research-terminal`
- Local database backup:
  `.runtime/backups/worldstate-v2-before-v3-a142d4ea9.db`
- The tag and archive branch were pushed to `origin` before migration work began.

## Historical runtime baseline

The entries in this section describe the frozen pre-v3 system only. They are
not current launch instructions; current launch instructions are in
`docs/desktop/windows.md`.

- Launcher: `WorldState.bat start`
- Desktop launcher at the captured commit: `WorldStateApp.bat` (then a PySide
  shell; now replaced by the consolidated Tauri/BAT chain)
- Frontend: `http://127.0.0.1:4173/?lang=zh&view=overview`
- Macro API: `http://127.0.0.1:8000`
- Methodology: `wst-state-v1`
- CPI Event Lab methodology: `cpi-event-lab-v1`
- CPI events: 9
- Market bars: 18,963
- Event-window metrics: 693
- Event analyses: 9
- Demo CPI event:
  `0525dad4-8d45-45ed-8e76-f47d22f3ad90`

The migration baseline screenshot is
[migration-baseline-overview.png](./assets/migration-baseline-overview.png).
It shows the eight-workspace, news-first product surface that is being replaced.

## API response fingerprints

Response bodies were hashed as UTF-8 bytes. Generated timestamps make the
health hash a point-in-time fingerprint rather than a stable contract.

| Endpoint | Status | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `/v1/health` | 200 | 960 | `0335f5d7c345a221e237ed23864478220dc13b71de037cd6fa14d3462e667361` |
| `/v1/events/lab/status` | 200 | 582 | `de209d61c52b8f651285201b6631c3b85c4f544c844a38cc9f11f03150b6d013` |
| `/v1/events?event_type=US_CPI` | 200 | 8,453 | `496eaee8294c73b56eff0d3fda3b6aa9af477e1934ee37bba4754b3115721b94` |
| `/v1/events/0525dad4-8d45-45ed-8e76-f47d22f3ad90` | 200 | 174,106 | `7d0c2f2f8a87c396d30ef5e2a86d5b7dabd759b29e0cccbab871512ca714815a` |

The old API did not provide separate `/analysis` or `/windows` resources for an
event. Both returned 404 and their content was embedded in the large event
detail response.

## Database v2 row counts and content fingerprints

The following values were computed from the immutable backup, not from the live
database after services restarted. Each table hash is over rows sorted by all
columns and encoded as canonical JSON lines.

| Table | Rows | SHA-256 |
| --- | ---: | --- |
| `alembic_version` | 1 | `bdd16370e9fee283fbcc2d3d4447db4c40102325ee10883e4bbbdc2325cee0f9` |
| `causal_edges` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `causal_nodes` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `consensus_snapshots` | 36 | `f1020b2d16dc644c8c2dc72f1b0f7afd7dde8f9105ec0dfab88afebb369c97a8` |
| `data_quality_records` | 81 | `28f162b148909b7494976627381347d300650618dd663b73672fde35e777b54d` |
| `economic_entities` | 1 | `c3bf3d4348072381380673992b3893d14bf0e2f9bd3532347c59d22d528e5230` |
| `event_analyses` | 9 | `3d56d749f6339ba310c9ad5dbd4a7896c32cb41b71156a4c99d758e0fee77531` |
| `event_indicators` | 36 | `0d111b358ffeb29bc3eb5ff53a6570effb6f826235c991dec578420d306e05d3` |
| `event_window_metrics` | 693 | `39faf6a850ed93b231d662c043615826f89929ecd00e882a31246208480498ff` |
| `macro_events` | 9 | `b191db95c54dd45e47cd413ce9b76fa4b354049b5cd8bf277dee1ce3175dcf7a` |
| `market_bars` | 18,963 | `db91f120b324ddd3191922f1e35395be4f3e48f5fd77b7bfc7f3f13e5cf1f3a5` |
| `market_instruments` | 7 | `951a5c0236e7e4d54914a6f0028521090bf979b520b9f35a0fba4cd7d113bbd1` |
| `observations` | 10,132 | `91d16c370f71d713918d363c54ddd169331e80a07e3b3120af3400487ddb6c4b` |
| `providers` | 1 | `998dfc6fa46e687694aed9c7500b41b63bfefb24d8ccf05f221202573199348e` |
| `release_series` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `releases` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `series` | 38 | `246f45813b4954d7a7f9399a80fa73b14bee0f71648d08619dc162eabc3fbf44` |
| `state_components` | 38 | `950d0f183d96a4b1df4f7d445a64f02ef01a7c7927eda4ae4e7a81e6b80525c0` |
| `state_definitions` | 8 | `03307d3e20186f3af8adea120a8415d02a41375a0b9958d0974c8fe067f4da83` |
| `state_snapshots` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `sync_runs` | 20 | `4d7e93f080deb9f334dbb3364137136861d57f13bb6e4e031b47cad9b720676f` |
| `theses` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `thesis_conditions` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `thesis_evidence` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `thesis_snapshots` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Validation baseline

- Backend: 58 tests passed, 85.43% coverage.
- Frontend macro build: passed with Vite 6.4.3.
- Legacy build transformed 2,364 modules and generated 237 PWA entries
  (10.67 MB).
- Largest legacy chunks included Globe/MapLibre/DeckGL and the monolithic App,
  confirming that non-macro World Monitor code remained in the shipped bundle.
- Known warning: one Starlette/httpx deprecation warning.

## Equivalence policy

Migration equivalence does not mean retaining every old screen. It means:

1. all nine CPI releases and their indicator values remain traceable;
2. all 18,963 market bars remain attributable to an instrument and source;
3. all 693 window metrics remain reproducible or are migrated with provenance;
4. the old CPI detail can be reconstructed from API v2 resources;
5. discarded empty World Monitor tables are explicitly listed in the migration;
6. no migrated fixture, manual consensus, or proxy instrument is presented as
   official or original data.
