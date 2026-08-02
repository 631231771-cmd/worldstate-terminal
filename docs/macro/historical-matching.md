# Historical matching

Historical comparison uses a versioned, fixed filter recipe:

1. same event family;
2. same surprise direction;
3. adjacent surprise-magnitude bucket;
4. regime dimensions actually available on both AnalysisRun-linked snapshots;
5. a fixed contamination policy (exclude high/unclean windows and score the
   remaining contamination match).

The response reports the population before and after filtering, conditions,
similarity, sample count and reliability.
The API also returns every used and missing dimension and each dimension's
weighted contribution. Two absent regime sets are missing data, not a 100%
match. Volatility regime is used only when a persisted value exists; the engine
does not synthesize a default value.

| Matched sample | Output |
|---:|---|
| 30+ | robust descriptive statistics |
| 15–29 | limited statistics with warning |
| 5–14 | case studies only |
| <5 | insufficient; no probability or percentile |

Filters cannot be added after observing the current market move. “Up
probability” is descriptive of the selected historical sample, not a forecast.
