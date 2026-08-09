# Event windows

Windows are anchored to each release stage, not merely a release date.

| Window | Interpretation |
|---|---|
| T-60m → T0 | pre-event drift |
| T-15m → T0 | immediate positioning |
| T0 → T+1m | first available reaction |
| T0 → T+5/15/30/60m | intraday transmission |
| T0 → T+4h | extended session |
| T0 → session close | event-day settlement context |
| T0 → next close | next-session persistence |
| T0 → five trading-day close | medium-horizon persistence |

Returns use percent change for prices and basis-point change for yields. Each
result stores start/end, maximum favorable/adverse excursion, volatility,
available volume change, reversal flags and data coverage.

Session helpers resolve America/New_York daylight saving time, weekends,
exchange holidays and close boundaries. Futures symbols and roll metadata are
stored separately. Where the imported file is a proxy or continuous contract,
that identity remains visible.

With minute bars, leading order means the earliest bar that exceeds a minimum
move and its pre-event volatility threshold for consecutive observations. It
does not reveal sub-minute order flow.
