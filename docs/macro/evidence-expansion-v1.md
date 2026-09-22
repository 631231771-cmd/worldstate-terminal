# Evidence Expansion v1

Implemented 2026-09-21. This is an additive evidence upgrade, not an event-price feed or causal identification model.

## Use

Open Research Memory → Macro Reasoning. Select the existing confirmed claim,
choose **更新官方证据**, then run its assessment. Each mechanism displays directional
evidence, background context, and positioning risk separately. Expand evidence
details for official links, observation IDs, proxy and current-version limitations.
The sync endpoint is `POST /v2/reasoning/evidence/sync`; existing local write
authorization applies. Refresh is user-triggered, with a persistent six-hour cache
(also covering failed attempts). No new scheduler or API credential is required.

## Official inputs actually acquired

| Source | Local series | Observations | Latest observation | Scope |
|---|---:|---:|---|---|
| EIA WPSR | 6 | 12 | 2026-09-11 | Commercial crude stocks excluding SPR, production, imports, exports, refinery utilization, products supplied |
| U.S. Treasury | 9 | 1,620 | 2026-09-18 | Nominal 2/5/10/30Y; real 5/7/10/20/30Y, current calendar year |
| New York Fed | 3 | 269 | 2026-09-18 | SOFR, underlying volume, overnight reverse repo accepted amount |
| CFTC | 18 | 3,492 | 2026-09-15 | Legacy futures-only noncommercial net, open interest, net/open-interest share for gold, WTI, 2Y/10Y Treasury, E-mini S&P and EUR |
| Total | 36 | 5,393 | | All observed; seven raw artifacts; no fixture substitution |

Official references: [EIA weekly petroleum](https://www.eia.gov/petroleum/supply/weekly/),
[Treasury XML feeds](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed),
[NY Fed reference rates](https://www.newyorkfed.org/markets/reference-rates),
[CFTC reporting portal](https://publicreporting.cftc.gov/).
Exact export URLs and content hashes are retained in SourceArtifact and ProviderRun.
EIA uses its official table1/table9 CSV exports, avoiding a credential requirement.
The CFTC query is restricted to six explicit contract-market codes, three years,
and a hard row limit; a potentially truncated response is rejected.

## Truthfulness and method

- Reuses Provider, Series, Observation, QualityRecord, ProviderRun and SourceArtifact.
  No database migration or parallel evidence storage layer was introduced.
- All imported history is **current-version/non-PIT**. `available_at` is the real
  acquisition timestamp, never the historical period date. An assessment before
  acquisition cannot see the export. Vintage is acquisition date, not first release.
- Raw exports, normalized record hashes and complete selected input values enter
  assessment provenance. Playbook definition/hash, matcher version and input/output
  hashes are frozen in each assessment. Old assessments are not recalculated.
- Same-day changed values are not overwritten in the existing daily-vintage model:
  the new artifact is retained, the sync is partial, and conflicts are counted.
  An operator must review these; intraday revision storage is not implemented.
- The matcher reads normalized local observations only, never external APIs.
  It filters mode, availability, acquisition, period and vintage by as-of.
- Changes use adjacent valid observations; excessive gaps and stale records become
  missing. Percentage-point yields/utilization changes are expressed as basis points.
- COT percentile compares current net/OI share with at most 156 previous weekly
  observations, excluding current, with a minimum of 104. Insufficient or constant
  samples do not produce a percentile. Net positioning and weekly net change remain
  distinct from percentile. COT categories do not identify institutional motives.
- Risk/context rules never vote in directional chain aggregation or directional
  supporting/contradicting ledgers. No confidence is interpreted as probability.
- Playbook 1.0.0 remains in source. New assessments use additive version 1.1.0;
  previously confirmed 1.0.0 mappings can be assessed without rewriting the claim.
  The old mapping and the new complete playbook are recorded together.

## Actual oil-case rerun

Existing user-authored confirmed claim, not an invented external-author opinion:
`0fafd9cc-bdfe-4f19-b8b8-b0ab8222cc2e`.
Assessment `a8f56f08-d2c7-4379-a955-edb50eff0f82`, as-of
`2026-09-21T13:42:35.074527Z`, playbook 1.1.0.
Output hash `55c349bb34d0d8209e6585abc8fb798514c0d4d4663848ca0fb5e3620db158cf`.

- Commercial crude stocks fell 0.640 million barrels: supports tightening, not
  proof of a supply disruption. U.S. production fell only 3 thousand barrels/day,
  below the declared 100-thousand threshold: neutral.
- Imports rose 234 thousand barrels/day; exports rose 1,414; refinery utilization
  fell 100 bp. These are context, not extra votes for the preferred narrative.
- Treasury 2Y rose 9 bp, 10Y rose 7 bp, real 10Y rose 7 bp in their latest sessions.
  Rates confirm the proposed direction, but not the oil-to-Fed causal link.
- Gold net/OI share is at approximately the 94.87th percentile of 156 earlier
  weekly reports: crowding risk only. Oil's corresponding percentile is 26.28.
- Existing WTI daily context rose 4.49%; Nasdaq 100 rose 0.67%, contradicting the
  proposed equity-pressure leg. Dollar and gold price inputs are stale/missing.
- Supply shock is **mixed**, three consecutive supported steps of six, not
  confirmed. Demand acceleration has more directional consistency in this
  snapshot; dollar/liquidity easing is mixed. These are competing checks, not a
  model ranking or proof that demand caused the move.

Weekly physical data and daily prices are from different dates, explicitly shown
per check. This is a current-context assessment, **not** synchronized intraday
event attribution. Other existing feeds refreshed during development, so do not
attribute every difference from an earlier assessment solely to the new sources.

## Still missing

### September 22 desktop validation update

The production Windows Tauri executable and its bundled Python executable were
launched against the existing `.runtime/worldstate.db`. The real WebView origin
was `http://tauri.localhost`; health returned v2/database ok. In the actual desktop
UI, **更新官方证据** completed all seven exports, then **使用最新数据重新检查**
created assessment `a0552cbb-040d-45e9-a8a8-933373345828` at
`2026-09-22T07:35:37.899132Z`, output hash
`a1e4e0545a5015c2e15516e41d822a3a8b11a7b5e9e46238d843cb9d84a66aee`.
The rendered source/claim, competing mechanisms, supporting/contradicting/missing
ledgers and per-input dates were read directly from the native WebView.

The second capture adds a new acquisition-date vintage: 10,796 observation rows,
but only **5,403 distinct series-period observations** across the same 36 series.
Do not count repeated acquisition versions as additional historical samples.
Treasury nominal/real curves now extend to September 21: 2Y unchanged, nominal
10Y -5 bp, real 10Y -6 bp. The supply hypothesis remains mixed and continuous
support stops at step 2/6, with these rates becoming counterevidence. Gold remains
stale; Nasdaq's new daily +2.83% also contradicts equity pressure. The former
September 21 assessment above remains available unchanged.

### Remaining scope limits

Global supply disruptions, OPEC actions, futures curve/backwardation, physical
regional spreads, policy-rate expectations and synchronized fresh gold/USD inputs
remain gaps. Products supplied is an apparent-demand proxy, not final consumption.
NY Fed scope here is SOFR and ON RRP, not a complete repo/funding-stress system.
EIA starts with two weekly observations; it is not a historical stock percentile.
Historical exports do not provide first-print vintages. Weekly COT cannot explain
minute moves. No minute data purchase or CPI consensus/release modification occurs.

## Validation

Parser, source artifact/idempotence, as-of and mode isolation, freshness, bp units,
minimum percentile samples, exclusion of current percentile sample, and exclusion
of risk/context votes have regression tests. Existing reasoning reproducibility,
API and UI flows remain covered. Runtime acquisition used the existing database
`.runtime/worldstate.db`, not a replacement empty database.
