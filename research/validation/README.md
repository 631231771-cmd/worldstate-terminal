# Migration validation

After running database v3:

```powershell
python research/validation/verify_migration.py .runtime/worldstate.db
```

The script verifies the required v3 tables, referential integrity for release
values and market bars, reports row counts, and prints a SHA-256 fingerprint.
It performs no writes.
