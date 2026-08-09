# Futures and rolls

`MarketInstrument` identifies the economic series; `FuturesContract` identifies
a dated contract and its valid interval. Market bars point to the normalized
instrument and retain provider symbol metadata.

Continuous futures and ETFs are proxies unless the source provides a documented
roll-adjusted series. The UI shows the proxy target and quality. Event windows
that cross a roll or session gap are flagged rather than blended silently.

The first release supports imported GC, SI, CL, ES, NQ, ZT and ZN-style minute
bars plus explicitly labelled yield/index alternatives. Production-grade
contract selection and volume-based roll automation remain provider work.
