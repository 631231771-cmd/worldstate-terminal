# ATAS local GC bridge PoC

Status: ATAS indicator loaded, **live quote path not yet validated** (2026-09-24).
This is an optional UI-only experiment, not an activated research provider.

## Scope and safety

`ATAS existing connection → WorldStateBridge indicator → ws://127.0.0.1:8000/v2/product/local-bridge/gc → ephemeral normalized quote → Market Desk`.

- Both gates are off by default: API environment `ATAS_LIVE_BRIDGE_ENABLED=1`
  **and** indicator property `Enable local GC bridge=true`. Without both, no stream.
- API binds `127.0.0.1`; the WebSocket rejects non-loopback peers and browser
  Origins. The indicator has a literal loopback URL. It does not use Rithmic
  credentials or create a second login. No cloud endpoint or file export.
- Only a concrete GC chart **month** is accepted (`GCZ6`, for example), not
  an undated continuous alias. ATAS may display `#GCZ6` on a continuous chart:
  the bridge preserves that exact `source_symbol` and identifies the current
  month as `GCZ6`, while the UI discloses the chart mode. If ATAS rolls the
  chart while the indicator is attached, sending stops rather than relabeling
  old observations. Exchange is included only when ATAS provides it. Trades
  and best bid/ask retain distinct SDK callbacks.
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
Select a *specific* GC contract; do not select a synthetic continuous chart.
Enable the indicator's local bridge property only after confirming the GC chart.
Do not restart ATAS or change its Rithmic connection merely for this step.

Start the WorldState Research API with `ATAS_LIVE_BRIDGE_ENABLED=1` in **its
process environment before startup**. Changing the variable after the API is
already running does nothing. The Desktop passes inherited environment to its
child API, but if an older API already owns port 8000 it must be stopped and
restarted normally. Never stop a working session without checking it first.
`GET /v2/product/live-gc` reports enabled/connected/last-seen state; the
Market Desk shows `GC <contract>`, bid/ask, event/receive clocks and current
1m OHLCV only while the quote is fresh. With the gate off, the page is unchanged.

## Validation boundary

On 2026-09-24 the user opened the `#GCZ6@COMEX` chart and approved loading
the locally compiled indicator. ATAS imported `WorldState Bridge (GC)` (its
indicator count rose from 283 to 284); it was added to that chart, the local
bridge checkbox was visibly checked, and Apply closed the settings dialog.
The WorldState API gate was enabled for the test, yet `/v2/product/live-gc`
remained `connected=false` with no quote. Neither ATAS nor WorldState reported
a verified market packet. The chart still displayed `Delayed 15m` in its
accessibility text, while the user-shown Rithmic connection itself was active;
that is not sufficient to prove which feed supplied the chart. No price/time,
reconnect or CPU comparison can be claimed.

After this observation, source was adjusted to retry startup on the first
live trade/quote callback and to consider the SDK's dated chart-symbol
fallback. The adjusted DLL builds with zero warnings, but ATAS has **not**
reloaded or validated that newer build. Windows window capture then failed
repeatedly when reopening the chart settings; we stopped UI input instead of
guessing at controls. The API was restarted normally with the bridge gate
**off** (`enabled=false`, `connected=false`) and the existing runtime DB was
retained. The user may remove the attached indicator in ATAS; it cannot send
to WorldState while the API gate is off.

Before calling this a real live feed, load the newer DLL safely, inspect one
concrete GC chart and compare ATAS vs WorldState last price, bid/ask, contract,
event/receive timestamps, 1m OHLCV, disconnect/reconnect and ATAS CPU/stability
over a non-trivial interval. Record whether that chart itself is live, delayed
or unverified. Do not infer chart feed freshness from the Rithmic login badge.

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
