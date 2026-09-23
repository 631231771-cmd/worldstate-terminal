# ATAS / Rithmic read-only feasibility spike

Checked 2026-09-23. This is a boundary decision, not an activated market feed.

## Local and product state

- Classic ATAS 8.0.14.399 is installed at `E:\ATAS Platform`; its documented
  `ATAS.Indicators.dll` is present. The .NET SDK is installed. No ATAS or
  R | Trader Pro process was running during this check. We did not open ATAS,
  inspect connector secrets, alter its settings, or start another Rithmic session.
- WorldState's current quote path is display-only public/indicative data.
  It does not create verified contract bars or event-research inputs. The
  workbench already consumes a normalized quote model rather than Rithmic
  fields directly.
- No observed ATAS/Rithmic tick, bid/ask, or one-minute data has been acquired
  by WorldState. The 30-day trial is not a durable provider commitment.

## Official paths checked

| Path | Technical finding | Current decision |
| --- | --- | --- |
| ATAS custom indicator | The [official SDK guide](https://docs.atas.net/en/md_DataFeedsCore_2Docs_2en_20010__BasicIndicator.html) describes a C# indicator loaded into ATAS; [market-data documentation](https://docs.atas.net/en/md_DataFeedsCore_2Docs_2en_20025__ReceivingProcessingData.html) exposes trade callbacks, and the [subscription interface](https://docs.atas.net/en/interfaceATAS_1_1Indicators_1_1IMarketDataSubscription.html) exposes trades and best bid/ask. This would use ATAS's existing connection, not a second login. | Preferred *technical* PoC candidate, but do not install a bridge or transmit data out of ATAS until the user's data rights are confirmed. |
| R | Trader Pro Plugin Mode | [Rithmic](https://www.rithmic.com/platforms/guides) and [ATAS](https://help.atas.net/en/support/solutions/articles/72000602593) document how multiple supported platforms share a feed without disconnecting the first. | A session-sharing mode, **not** a market-data API or proof of WorldState entitlement. Do not change the user's working connection just for the spike. |
| Rithmic developer API | [Rithmic's API page](https://www.rithmic.com/apis) describes R | API+ and R | Protocol, a requested dev kit, and conformance before production access. | No evidence that the current trial includes developer access. Do not reuse the ATAS username/password to create a second client. |
| ATAS CSV export | The documented [All Prices export](https://help.atas.net/en/support/solutions/articles/72000602578) is an interactive volume-at-price CSV, not a supported live quote bridge. | Not suitable for the proposed real-time test. |

The [ATAS license](https://atas.net/license-agreement/) distinguishes use of
the software from rights in third-party market data and restricts use of data
outside the granted terms. The public documents above do not explicitly grant
this Rithmic trial's data export to another application. This is a permission
uncertainty, not a claim that local personal display is prohibited.

## Safe next gate

Before a live bridge, confirm with the trial issuer / broker and ATAS or
Rithmic that a private, read-only ATAS indicator may send GC/CL/ES/NQ/ZT/ZN
trade, best bid/ask and one-minute OHLCV to a second application on the same
machine, with no redistribution, trading, or cloud upload. Also confirm which
contracts and exchange entitlements the trial actually covers.

If allowed, keep the proof small: an opt-in indicator attached to one chart,
bounded localhost-only transport, no credentials, a short-lived local buffer,
explicit source/contract/timestamp/granularity, and UI-only quotes. Observe
ATAS CPU/session stability before adding other instruments. Do not write this
feed to `MarketBar`, `MarketDataManifest`, or `AnalysisRun` until provenance,
contract identity, rights and replay semantics have separate validation.
ZT/ZN would be Treasury **futures prices**, never yield changes in bp.
