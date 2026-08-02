# Surprise calculation

For indicator \(i\):

- raw surprise: `actual - consensus`
- relative surprise: `(actual - consensus) / max(abs(consensus), tolerance)`
- standardized surprise (`surprise_z`): `(oriented_surprise - historical_mean) /
  historical_forecast_error_sigma`
- threshold scale (`threshold_scaled_surprise`): `oriented_surprise /
  predeclared_indicator_tolerance`

Indicator metadata defines whether a positive number is hotter/stronger or has
the opposite economic meaning. Values inside release-specific tolerance are
neutral.

Bundle classification uses the same predeclared indicators and weights for
every event of a type. CPI evaluates headline/core and month/year measures
separately before assigning broad-hot, broad-cold, core-hot, headline/core
conflict, month/year conflict or revision-dominated labels. Nonfarm payrolls
combine payrolls, unemployment and wages. FOMC uses decisions and stages rather
than treating the evening as one scalar.

`surprise_z` requires at least 20 point-in-time forecast errors strictly before
the current release and non-zero variance. If either condition fails it is
`null`; the threshold-scaled value is never labelled or rendered as a Z-score.
The run stores sample count, mean, standard deviation and cutoff time.

NFP revisions are first transformed on each indicator's own scale and then
weighted. A revision-dominant classification is allowed only when at least two
components have genuine Z-scales. With only threshold scales, the UI names the
revised indicators but says cross-indicator dominance cannot be established.
