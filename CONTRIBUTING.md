# Contributing

Changes should strengthen the macro-event research workflow, preserve
point-in-time semantics and keep data provenance visible.

Before opening a change:

1. Run the Python lint, type and test commands in `README.md`.
2. Build `apps/terminal-ui`.
3. Add a migration for schema changes and validate it on a clean database.
4. Add source, capture time and quality metadata for every new provider.
5. Document copied or adapted third-party code in `THIRD_PARTY_NOTICES.md`.

News aggregation, maps, trading execution and portfolio management are outside
the current product boundary unless a later architecture decision explicitly
brings them back.
