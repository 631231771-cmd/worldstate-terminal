# Trading-calendar limitations

Event-window coverage is calculated from expected tradable minutes, not raw
elapsed minutes. v0.4 uses `exchange_session_lite`: US cash hours, US DST,
weekends, Good Friday, selected early closes and a CME/COMEX/NYMEX-style
17:00–18:00 ET maintenance interval. It is not a licensed complete exchange
calendar. Sunday evening reopening and Friday shutdown are represented for CME
and 24x5 FX research windows. Each instrument selects its declared calendar,
and next-day/fifth-day endpoints advance on that calendar rather than natural
days.

Long windows, early closes and continuous-contract analysis remain
experimental. Product-specific settlement times, every exchange notice,
weather/emergency closures and licensed expiry/roll schedules are not complete.
The API and Event Lab therefore label the calendar name, `exchange_session_lite`
precision, expected tradable bars and coverage with every window.

Short event windows use one-minute bars. T+1/T+5/session horizons use a daily or
provider-declared session-close observation only. Databento `ohlcv-1d` is a
UTC-day aggregate and is therefore disclosed as an experimental grade-C proxy,
not an exchange settlement/close. If daily semantics cannot be established, the
window remains unavailable rather than falling back to the last arbitrary bar.
