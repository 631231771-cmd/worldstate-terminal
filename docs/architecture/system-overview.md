# System overview

WorldState is a modular monolith. Domain packages are independent of HTTP,
storage and external provider schemas; the application layer coordinates them.

```mermaid
flowchart LR
  UI["Terminal UI / Tauri"] --> API["FastAPI /v2"]
  API --> APP["Application services"]
  APP --> MC["macro_core"]
  APP --> MK["market_core"]
  APP --> EE["event_engine"]
  APP --> RE["research_engine"]
  APP --> AI["ai_researcher"]
  APP --> DB[("Database v3")]
  APP --> PK["provider_kit"]
  PK --> OFF["Official / optional providers"]
  PK --> CSV["CSV / fixture"]
  AI --> EP["EvidencePack only"]
```

`macro_core` owns indicators, releases and regimes. `market_core` owns
instrument identity and session rules. `event_engine` computes surprises and
event windows. `research_engine` matches historical cases. `ai_researcher`
validates and summarizes an EvidencePack. Provider and database models do not
become domain contracts.

The architecture-boundary test parses imports and fails when a foundational
package depends on a higher layer or when a legacy World Monitor domain returns.
