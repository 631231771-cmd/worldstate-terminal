# Macro Research Terminal v3 progress

The product/activity-tree migration is complete. Research-method and release
stabilization is tracked in [`v0.4-stabilization.md`](v0.4-stabilization.md).

Completed:

- database v3 and one-time v2 backfill;
- CPI, nonfarm payroll and four-stage FOMC fixtures;
- point-in-time values and consensus snapshots;
- market-bar import, event windows, reversal and earliest-reaction analysis;
- fixed historical matching and sample-size degradation;
- contamination, quality, proxy and fixture controls;
- EvidencePack-constrained explanations and optional assistant;
- FastAPI `/v2`, five-workspace terminal UI and Tauri shell;
- Python tests, architecture boundaries, CI and migration validation.

Next highest-value work:

1. licensed real-time/archival minute market provider;
2. durable pre-release consensus capture workflow;
3. official BLS/BEA/Federal Reserve release parsers;
4. frozen Python sidecar and signed desktop installer;
5. larger point-in-time history for reliable regime-conditioned statistics.
