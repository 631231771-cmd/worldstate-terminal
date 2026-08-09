# Data quality and provenance

Data quality is a domain record, not a decorative badge. Important inputs can
retain source/provider, source URL, retrieval/capture/availability timestamps,
manual verification, fixture/proxy flags, delay, granularity, missing reason,
quality grade, raw artifact hash and the Provider/Sync run that produced them.

## Data modes

v0.5 makes `data_mode` part of the identity and query boundary for releases,
release values, consensus snapshots, market bars, analysis runs, Provider runs,
source artifacts, manifests, calendar snapshots, reconciliation records and
backfill/sync state.

- `observed`: obtained or entered as a real-world observation. It may still be
  manual, delayed, unverified, revised, incomplete or low quality.
- `fixture`: traceable demonstration/test data. It cannot satisfy observed
  coverage or enter an observed analysis cohort.

The same release type and timestamp may exist in both modes. Coverage, history
and analysis queries keep the modes isolated. UI/API must show the selected
mode; a fixture badge is not optional.

## Grades

Grades summarize fitness for a specific method:

- **A**: authoritative/directly verified, point-in-time and fit for the stated
  calculation.
- **B**: reliable but delayed, manually verified or carrying a limited field
  gap.
- **C**: proxy, coarse or partially verified; usable only with visible caveats.
- **D**: fixture or materially incomplete; demonstration/case context only.
- **UNKNOWN**: persisted input exists but has not received a defensible grade.
- **unavailable**: required input is absent; the affected calculation must not be
  emitted.

A Provider being “configured” or “healthy” does not grant grade A. Provider
status, entitlement, quota, data coverage and methodological fitness are
separate dimensions.

## Point-in-time rules

- Release values and consensus snapshots are append-only snapshots.
- Surprise calculations select consensus captured strictly before T0.
- A current BLS series response is not labelled as a historical first release.
  BLS Public Data API is not a complete historical vintage archive.
- ALFRED realtime periods/vintage dates can support historical information sets,
  but require a configured FRED key and still need source-specific validation.
- A post-release Trading Economics calendar value cannot be reconstructed into a
  pre-release survey snapshot when PIT access was unavailable.

## Proxy and instrument semantics

- DX and VX are futures, not cash DXY and VIX.
- ZT and ZN are Treasury-futures price proxies. Their price moves are not exact
  2-year or 10-year cash-yield basis-point moves.
- Contract, venue, dataset, source symbol, resolved symbol and roll state belong
  in a market-data manifest. Bars from different contracts are not silently
  concatenated.

## Coverage and contamination

Coverage is reported separately for actual values, pre-release consensus,
intraday bars and daily/session-close data. A release count alone is not proof
that an analyzable event window exists.

Every dimension distinguishes `stored` from `analysis_eligible`. Stored records
can be `stored_not_eligible`: examples include a revised current BLS value that
cannot reconstruct the first print, a TE snapshot captured at/after T0, or a
market manifest without rows, grade A–C and a passing integrity reconciliation.
Only `analysis_ready` rows enter the default research selector.

Contamination remains separate from source quality: perfectly sourced prices can
still be weak evidence for attribution when another release or headline overlaps
the window. Contamination, missing benchmark assets, coarse bars, low coverage,
proxy use and cross-asset disagreement reduce confidence and restrict causal
language.

## Current implementation truth

The v0.5 schema, persistence helpers, provider orchestration, scheduler/worker,
coverage endpoint and automatic persisted-data reconciliation are implemented.
An empty or `stored_not_eligible` observed matrix remains an honest result when
credentials, PIT history, licensed market data, first-print reconstruction or
integrity checks are missing; fixture never fills those gaps.

Official-vs-TE reconciliation compares release time, Actual, Previous, Revised,
unit and reference period while retaining both artifacts. A mismatch lowers TE
quality and never overwrites the official value. Overnight reconciliation reruns
saved comparisons and merges market checks, so a weak count check cannot erase
ingestion-time contract, OHLC, gap, timezone, roll or session evidence.
