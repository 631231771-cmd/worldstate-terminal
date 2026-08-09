# Trading Economics consensus

Trading Economics is an optional licensed source for the US CPI, NFP and FOMC
calendar/consensus chain. It is a secondary comparison source, not the authority
for official actual values.

## Implemented adapter policy

- `Forecast` is survey consensus.
- `TEForecast` is retained separately as Trading Economics' proprietary forecast.
- Surprise calculations use only the last qualified survey-consensus snapshot
  captured strictly before T0.
- A proprietary forecast never fills a missing survey consensus.
- `Actual`, `Previous` and `Revised` can support reconciliation but cannot
  overwrite BLS or Federal Reserve values.

The adapter normalizes CalendarId, ticker, event, reference, source, unit,
LastUpdate, capture time, PIT query date and raw response hash. It supports date
batching, explicit PIT-entitlement errors, quota metadata and deterministic
selection of the last pre-release snapshot.

Adapter semantics have mocked-response tests and `snapshot-consensus` persists
calendar snapshots, eligible consensus, raw artifacts, quota/entitlement and
quality. The current environment has no Trading Economics key, so live account
and PIT entitlement remain unvalidated and the command honestly returns blocked.

## Snapshot policy

Capture targets are T-24h, T-1h and T-5m, plus a T+5m audit snapshot. When a job
runs on time it uses the current calendar response. Only a missed/delayed replay
sets `pit_at` to the scheduled time and requires historical PIT entitlement.
Absent entitlement is stored as a gap; WorldState never reconstructs a missed
pre-release consensus from a post-release current response.

Health/status is quota-free by default. A configured key is reported as
`configured_unverified` without calling a calendar endpoint or incrementing
quota. A real successful snapshot—whose response quota is persisted—is the live
health evidence.

The service cross-checks official release time, Actual, Previous, Revised, unit
and reference period against TE while retaining both artifacts. A mismatch
lowers TE quality; it never overwrites BLS/Federal Reserve authority.

Official references:

- <https://docs.tradingeconomics.com/economic_calendar/point-in-time/>
- <https://docs.tradingeconomics.com/economic_calendar/schema/>

Trading Economics content remains subject to the account's subscription and
licence. Raw responses, quota state and account-derived data stay local and are
not committed or exposed for redistribution.
