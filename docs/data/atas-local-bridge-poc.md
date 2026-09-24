# ATAS local GC bridge PoC

Status: root-only display quote received and rendered in Market Desk on
2026-09-24; dated contract identity and entitlement remain unverified.
This is an optional UI-only experiment, not an activated research provider.

## Scope and safety

`ATAS existing connection → WorldStateBridge indicator → ws://127.0.0.1:8000/v2/product/local-bridge/gc → ephemeral normalized quote → Market Desk`.

- Both gates are off by default: API environment `ATAS_LIVE_BRIDGE_ENABLED=1`
  **and** indicator property `Enable local GC bridge=true`. Without both, no stream.
- API binds `127.0.0.1`; the WebSocket rejects non-loopback peers and browser
  Origins. The indicator has a literal loopback URL. It does not use Rithmic
  credentials or create a second login. No cloud endpoint or file export.
- A concrete SDK GC contract (`GCZ6`, for example) is preserved if available.
  On the user's existing `#GCZ6` chart the public indicator SDK instead returns
  only `GC`. For this case the bridge may emit **UI-only** root identity:
  `source_symbol=GC`, `contract=null`. The workbench prominently marks the
  contract month unverified; it must not infer `GCZ6` from the toolbar or use
  the quote for event research. With only root identity, a chart roll cannot
  be distinguished by the SDK, so even the in-memory graph is not a verified
  single-contract series. Exchange is included only when ATAS provides it.
  Trades and best bid/ask retain distinct SDK callbacks.
- Only the latest trade/size, best bid/ask and an in-memory 1m OHLCV accumulator
  are sent at most once per second. There is no DOM, MBO, footprint, delta,
  iceberg, order routing or historical tick export. Disconnect marks the quote
  stale; the page falls back to its separate public indicative gold reference.
- Data is not written to `MarketBar`, `MarketDataManifest`, `AnalysisRun` or
  any event-research table. `event_research_eligible=false` is enforced.
  The trial's right to display exported data in a second local app remains
  unconfirmed; do not treat this PoC as permission or redistribute data.

## Build and local activation

The installed ATAS version used here runs .NET 10 and provides
`E:\ATAS Platform\ATAS.Indicators.dll`. Install a .NET 10 SDK if absent, then:

```powershell
dotnet build apps/atas-local-bridge/WorldStateBridge.csproj -p:AtasHome='E:\ATAS Platform'
```

The output is `apps/atas-local-bridge/bin/Debug/net10.0-windows/WorldStateBridge.dll`.
ATAS's official Indicators window can load a custom DLL into the current chart.
Use the existing GC chart; do not reopen another chart merely to obtain a
dated SDK identity. Enable the indicator's local bridge property only after
confirming it is a GC chart. Root-only data remain unverified display data.
Do not restart ATAS or change its Rithmic connection merely for this step.

Start the WorldState Research API with `ATAS_LIVE_BRIDGE_ENABLED=1` in **its
process environment before startup**. Changing the variable after the API is
already running does nothing. The Desktop passes inherited environment to its
child API, but if an older API already owns port 8000 it must be stopped and
restarted normally. Never stop a working session without checking it first.
`GET /v2/product/live-gc` reports enabled/connected/last-seen state; the
Market Desk shows a verified `GC <contract>` when available, otherwise a clear
unverified-month label, plus bid/ask, event/receive clocks and current
1m OHLCV only while the quote is fresh. With the gate off, the page is unchanged.

## Validation boundary and handoff (2026-09-24)

### Confirmed startup blocker (GPT-6-Sol diagnosis)

At 05:54:42 UTC the diagnostic revision was successfully instantiated in ATAS.
Its local lifecycle record shows `enabled=True`, `initialized`, followed by
`contract: rejected info=GC legacy=GC provider=present`. At 05:54:52 it also
received a real SDK `Trade` callback. Both instrument properties therefore
return the undated `GC` alias on this chart; the strict dated-contract guard
returns before creating the WebSocket sender. This is the observed startup
blocker. The currently running diagnostic instance loaded successfully, so the
earlier assembly warning does not explain this instance's failure to connect.

An independent .NET ClientWebSocket empty handshake with the real running
receiver succeeded and temporarily produced `connected=true`. No fabricated
market values were sent. The receiver and opt-in gate work. The later
root-only display correction removes the dated-ID requirement for this
operational quote only. Do not hardcode the toolbar month or relabel undated
data as a verified contract.

At 14:36 the new DLL was backed up and copied into ATAS's Indicators directory;
ATAS logged `Changed library` but the active instance did not reload itself.
Later the main-window bottom-right indicator-reload icon successfully refreshed
the library. Searching `WorldState` in the existing GC chart's Indicators
dialog found the bridge; it was added, enabled and applied. The new diagnostic
instance logged `accepted GC root`, connected WebSocket, real Trade callback
and snapshot sent. API `/v2/product/live-gc` showed a current live quote,
bid/ask and 1m OHLCV. ATAS's displayed 4316.8 matched the API's 4316.8 in a
near-contemporaneous check; Market Desk then visibly switched to the local
quote with an unverified-month label. Over 10 seconds the connection remained
up and receipt timestamps advanced. This validates the **UI-only operational
path**, not a dated contract identity, market-data redistribution rights or
reconnect handling. No historical/event data were imported.

The remaining paragraphs describe the earlier observations leading to that
diagnosis. Updated task prompt: `docs/data/atas-gc-bridge-handoff.md`.

The user opened `#GCZ6@COMEX` and approved the read-only indicator test. ATAS
imported `WorldState Bridge (GC)` and its settings showed `Added (1)` with
`Enable local GC bridge` checked; Apply closed the dialog. The revised DLL was
subsequently imported again. Its SHA-256 in ATAS's Indicators directory and
the build output are identical:
`BA67836EB429530FBF704354838794C1A9D523BC9424F5D3F99FFADA9065CBC6`.
This verifies the file, **not** that the currently instantiated indicator
successfully loaded/executed that revision.

The API health was 200 (`worldstate-terminal`, v2, database `ok`). The test
gate is currently enabled (`/v2/product/live-gc` reports `enabled=true`), but
`connected=false`, `last_seen_at=null`, `quote=null` after Apply and another
short wait. No WebSocket session or market packet has been verified, so no
price, timestamp, reconnection or CPU agreement can be claimed. No quote was
written to research tables.

Important correction: an earlier note interpreted ATAS's accessibility text
`Delayed 15m` as applying to the GC chart. The user's screenshot shows the
15-minute labels belong to *other* status-bar connections (ATAS Sim/dxFeed),
while the Rithmic connection displays fresh market-data updates. That earlier
delay claim was unsupported and must not be used as the bridge failure cause.

ATAS's 2026-09-24 log contains `Could not resolve type ... WorldStateBridge`
warnings at 13:08 and 13:16, before the latest import at 13:32. The log also
records `Changed library ... WorldStateBridge.dll` at 13:32; no later matching
load error was found in the inspected lines. The warnings are a diagnostic
lead, **not** proof that the latest instance failed for the same reason. The
remaining alternatives include indicator initialization, ATAS's actual
instrument identifier failing the strict dated-contract guard, or WebSocket
startup. The current indicator swallows socket exceptions to protect ATAS, so
the three cases are not yet distinguishable from the API response alone.

Next: do not ask the user to open another GC chart or blame delayed data.
Diagnostics and the root-only display correction are built and copied, but
ATAS has not reloaded the active indicator instance. Reload that one indicator
on the existing chart once; then check its diagnostic log and
`/v2/product/live-gc`. Only if `connected=true` and a fresh quote arrives,
compare the displayed price, bid/ask, event/receive timestamps, 1m OHLCV,
reconnect and ATAS stability. The contract month is **not** verified from
the indicator SDK. The current computer-use surface cannot operate the ATAS
main window; stop unsafe coordinate input rather than guessing.

## References and reuse

- [ATAS official indicator SDK](https://docs.atas.net/en/md_DataFeedsCore_2Docs_2en_20010__BasicIndicator.html)
  and [trade/bid/ask callback guide](https://docs.atas.net/en/md_DataFeedsCore_2Docs_2en_20025__ReceivingProcessingData.html): API contract only.
- [ATAS on continuous charts](https://atas.net/blog/continuous-futures-contract/):
  a continuous chart can show the current dated contract in its toolbar, but
  stitched history is not that contract's standalone historical series.
- [AtasPlatform/Indicators](https://github.com/AtasPlatform/Indicators),
  inspected `46c8a6ec8618cbf7297d6d1c6afb9162eb30df9a`: examples only;
  no source copied (repository did not expose a license in the inspected metadata).
- [ATASPythonSocket concept](https://gist.github.com/bukowa/821e248897dedead26027b9164305dd2):
  custom indicator → localhost socket → Python idea only; no source copied.
- [raoulsson/atas-extensions](https://github.com/raoulsson/atas-extensions),
  inspected `c869e73875c349986d1a5f92d1717475b9d305c9`, MIT: OHLCV exporter
  behavior studied; no source copied. WorldState uses .NET `ClientWebSocket`,
  not that project's exporter or `websocket-sharp`.
