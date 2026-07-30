# Surprise calculation

For indicator \(i\):

- raw surprise: `actual - consensus`
- relative surprise: `(actual - consensus) / max(abs(consensus), tolerance)`
- standardized surprise: `(actual - consensus) / historical_forecast_error_sigma`

Indicator metadata defines whether a positive number is hotter/stronger or has
the opposite economic meaning. Values inside release-specific tolerance are
neutral.

Bundle classification uses the same predeclared indicators and weights for
every event of a type. CPI evaluates headline/core and month/year measures
separately before assigning broad-hot, broad-cold, core-hot, headline/core
conflict, month/year conflict or revision-dominated labels. Nonfarm payrolls
combine payrolls, unemployment and wages. FOMC uses decisions and stages rather
than treating the evening as one scalar.

If forecast-error history is insufficient, standardized surprise is unavailable
or explicitly degraded; the engine never invents a denominator.
