# Analysis-run reproducibility

Every new v0.4 `AnalysisRun` records immutable release, consensus, stage and
full OHLCV minute-bar snapshots plus a content hash for the market data, historical
sample manifest, algorithm/rule versions, configuration hash and output hash.
The manifest is available at `GET /v2/analysis-runs/{id}/manifest`.

Runs migrated from v3 are deliberately marked `legacy_incomplete`: the system
does not invent historical hashes that were never captured. A replay request
recalculates market, history, configuration, input and core-output hashes from
the stored immutable snapshot and never substitutes later consensus, market
bars or historical releases. It returns an individual pass/fail check for every
layer. Replay verifies the versioned core result; running a future algorithm
version against the old snapshot is a separate migration operation.
