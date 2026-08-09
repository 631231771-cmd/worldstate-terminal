# Consensus snapshots

Consensus is a point-in-time object, not a mutable field on a release. Each
snapshot stores value, source, capture timestamp, quality, manual status and
verification notes.

Only snapshots captured before the release stage may be used in surprise
calculations. Later corrections append another record and never rewrite the
pre-event view. Manual and CSV inputs are valid when their provenance is clear;
they are not upgraded to “official” by the system.

Proprietary consensus files belong under `data/local` or `data/imports` and must
not be committed unless their redistribution license explicitly permits it.
