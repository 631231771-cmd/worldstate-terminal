# Data flow

```mermaid
sequenceDiagram
  participant P as Provider / manual import
  participant S as Source snapshot
  participant R as Macro release
  participant M as Market bars
  participant E as Event engine
  participant H as Historical research
  participant A as AI researcher
  participant U as Terminal UI

  P->>S: source, captured_at, quality
  S->>R: append values and consensus
  P->>M: normalized bars + proxy/fixture flags
  R->>E: point-in-time bundle at T0
  M->>E: stage-relative bars
  E->>H: surprise, regime, windows
  H->>A: facts, statistics, hypotheses, gaps
  A->>A: validate EvidencePack and wording
  A->>U: report with citations and confidence
```

If data is missing, the pipeline degrades explicitly: a window can be
unavailable, historical output can fall back to cases, and the report records a
gap. Missing data is never silently synthesized.
