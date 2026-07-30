# Providers

WorldState converts every source into its own release, consensus or market-bar
records. Provider schemas never become the database contract.

Current paths:

- manual release and consensus capture;
- CSV minute-bar import;
- traceable fixture provider for demonstrations and tests;
- optional FRED/ALFRED adapter;
- optional Macrosynergy analytics adapter;
- optional isolated OpenBB gateway.

Provider runs store operation, start/end, status, row counts, quality and error
details. Waterfall fallback continues after an optional provider fails. A
failure never silently changes an instrument into a proxy.
