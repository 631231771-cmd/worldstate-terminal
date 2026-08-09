# Domain model

The aggregate root is `MacroRelease`, not a news story.

```mermaid
erDiagram
  MACRO_RELEASE ||--o{ RELEASE_STAGE : has
  MACRO_RELEASE ||--o{ RELEASE_VALUE : publishes
  INDICATOR ||--o{ RELEASE_VALUE : identifies
  MACRO_RELEASE ||--o{ CONSENSUS_SNAPSHOT : freezes
  INDICATOR ||--o{ CONSENSUS_SNAPSHOT : forecasts
  MARKET_INSTRUMENT ||--o{ MARKET_BAR : records
  MACRO_RELEASE ||--o{ ANALYSIS_RUN : analyzes
  ANALYSIS_RUN ||--o{ EVENT_WINDOW_RESULT : computes
  ANALYSIS_RUN ||--o{ MARKET_REACTION : derives
  ANALYSIS_RUN ||--o{ HISTORICAL_MATCH : compares
  ANALYSIS_RUN ||--o{ EXPLANATION : constrains
  ANALYSIS_RUN ||--o{ REPORT_ARTIFACT : produces
```

Release values and consensus snapshots are append-only. Every derived artifact
is linked to an `AnalysisRun` with methodology and code versions. Source
artifacts and data-quality records preserve provenance. FOMC stages are separate
time anchors, so statement and press-conference reactions are never collapsed
into one overnight move.
