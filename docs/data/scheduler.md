# Local data scheduler

v0.5 starts a non-blocking local scheduler and recoverable backfill worker with
the Research API when `WORLDSTATE_SCHEDULER_ENABLED=true` (the default launcher
setting). It is an in-process desktop runtime, not a cloud daemon: work pauses
while the API/computer is off and resumes through bounded catch-up/recovery.

## Implemented primitives

The fixed schedule catalog contains:

- `daily-official-sync`
- `daily-calendar-sync`
- `daily-provider-health`
- `pre-release-consensus-snapshot`
- `post-release-official-refresh`
- `post-release-market-sync`
- `overnight-reconciliation`

`sync_jobs` stores the stable job/config/schedule; `sync_job_runs` stores
idempotency key, schedule/availability time, attempt, retry lineage, status,
heartbeat, checkpoint, record counts and safe error metadata. Service functions
can register defaults, enqueue daily/release-relative work, claim a due run,
retry/recover stale work and enqueue next/fifth-session market windows.

Consensus offsets are T-24h, T-1h and T-5m; T+5m is an audit target.
Post-release market targets include a partial early window, T+4h completion and
deferred next/fifth-trading-session data. Each run's durable result is the proof
of capture; a schedule definition alone is not.

On-time T-24h/T-1h/T-5m/T+5m jobs issue a current TE capture (`pit_at=null`). A
pre-release job first seen after T0, or a job delayed beyond the live grace
window, becomes an explicit historical replay at its scheduled timestamp and
requires PIT entitlement. The system never labels a post-T0 current response as
the missed pre-T0 snapshot.

## Runtime behavior and limits

The runtime dispatches official/calendar, consensus, official refresh, market
and reconciliation operations. First desktop startup schedules at most today's
missed daily occurrence rather than skipping to tomorrow or replaying an
unbounded history. Stale running attempts are checked every cycle, not only at
startup, and create durable retries. Backfill cancellation/progress and partial
manifests survive restart. Network/provider failures are stored per run and
cannot delay the health endpoint or block desktop startup.

`daily-provider-health` is configuration-level and quota-free. In particular it
does not call the TE calendar endpoint: it persists `configured_unverified` and
request count zero. A successful real sync is the online health evidence.
`overnight-reconciliation` calls the persisted reconciliation service; it does
not fetch TE again and it cannot replace rich market checks with a weaker pass.

Credentials must never be embedded in job arguments, checkpoints or logs; workers
must resolve secrets from the local configuration/keyring at execution time.
