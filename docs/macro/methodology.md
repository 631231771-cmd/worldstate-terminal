# Macro-event methodology

WorldState separates research logic from data acquisition. A completed analysis
run is reproducible from point-in-time release values, pre-event consensus
snapshots, event/stage market bars, regime state, method configuration and a
fixed historical cohort. Provider status alone is never treated as evidence.

## Analysis pipeline

1. Validate source, availability timestamp, data mode, quality and instrument
   semantics.
2. Select the consensus snapshot captured strictly before T0.
3. Compute indicator-level raw and relative surprise. Compute a genuine
   point-in-time Z-score only with at least 20 prior forecast errors and non-zero
   variance; otherwise expose the separately named
   `threshold_scaled_surprise` and leave `surprise_z = null`.
4. Classify the event bundle, for example broad hot CPI, headline/core conflict
   or an NFP revision that cannot yet be compared across units.
5. Calculate stage-relative market windows using only bars in the same data mode.
6. Detect volatility-adjusted earliest observed reactions, reversals,
   spike-and-fade and dip-and-recovery patterns.
7. Match history with a recipe fixed before viewing the outcome. Missing regime
   dimensions receive no default match credit; contamination is an explicit
   match/filter dimension.
8. Score multiple competing macro transmission hypotheses.
9. Build EvidencePack items and structured claims, then optionally ask AI to turn
   the validated structure into readable prose.

## Reproducibility

AnalysisRun manifests retain or hash the release/value versions, consensus IDs,
stage IDs, OHLCV input snapshot, source/Provider references, algorithm and rule
versions, historical cohort, parameters, configuration and output. Replaying an
old run uses its immutable manifest rather than silently querying the latest
database state.

Fixture and observed histories are isolated. A successful fixture replay proves
determinism of the workflow; it does not prove that real historical consensus or
minute data is complete.

## Explanations and AI

Claims distinguish confirmed facts, historical relationships and inference.
Each confirmed fact must bind to a valid Evidence ID; inference must carry
limitations and a falsifier. Fixture/proxy use must be disclosed. Unsupported or
over-causal AI output fails validation and falls back to deterministic claims.

The system never asserts that a single rule, fund, keyword detector or participant
caused a price move. It can report that observed cross-asset sequencing is
consistent with one transmission chain and compare competing explanations.

## Confidence penalties

Confidence falls with:

- contaminated or unclean event windows;
- missing benchmark assets or event stages;
- proxy/continuous-contract uncertainty;
- low-frequency, delayed or incomplete bars;
- insufficient historical samples;
- missing regime dimensions;
- cross-asset disagreement;
- manual/unverified or fixture inputs.

## Trading-calendar limit

`exchange-session-lite` accounts for US DST, weekends, Good Friday, selected
early closes and a simplified CME-style maintenance window. Long windows remain
experimental. This implementation is not a complete licensed exchange calendar
and does not claim every product settlement, emergency closure, expiry or roll
rule.

## v0.5 data-foundation boundary

Provider adapters, data-mode isolation, provenance manifests, durable job state,
cost policy, local scheduler/backfill worker and coverage presentation are
implemented in the v0.5 worktree. Official, consensus and market services write
durable artifacts and an AnalysisRun selects only release-linked manifest data.
For each instrument/granularity it selects one provider/contract/dataset/schema
identity, deterministically merges same-identity overlap and freezes the selected
manifest IDs and bars for replay. Consequently:

- fixture CPI/NFP/FOMC analyses are end-to-end demonstrations;
- manual/CSV observed workflows remain available;
- BLS public mode and Federal Reserve official sync are wired; Fed covers the
  2015–2020 archive plus current/future schedule. This validation network's BLS
  schedule HTML returned HTTP 403, while Fed public pages were verifiable;
- FRED/ALFRED, Trading Economics and Databento live validation is blocked in the
  current environment by missing credentials and, where applicable,
  subscription/entitlement;
- no “full real-data history” claim is valid for v0.5 at this checkpoint. Local
  automatic refresh runs only while the API is open and cannot bypass upstream
  access, cost or point-in-time limits.

Short-window and earliest-reaction calculations require one-minute data. T+1,
T+5 and session horizons require daily bars or a provider-declared session-close
observation. Databento `ohlcv-1d` is a UTC-day aggregate, not an exchange close
or settlement; it is capped at grade C and labelled an experimental proxy. If
daily semantics are absent or unknown, the engine emits a data gap rather than a
fabricated long-window return.
