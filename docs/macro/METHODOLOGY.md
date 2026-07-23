# World State methodology v1

Methodology ID: `wst-state-v1`.

This method is a transparent monitoring heuristic, not a forecast, trading
signal, or investment recommendation.

## Point-in-time input

Each observation is uniquely identified by series, observation period, and
vintage date. A query with an `as_of` timestamp first removes any row whose
`available_at` is later than that timestamp, then chooses the newest remaining
vintage for each period. Transforms run only after this filter, so a later
revision cannot leak into an earlier historical view.

Missing provider values remain missing. They are never forward-filled or
converted to zero by the state engine.

## Components and transforms

The U.S. catalog contains 38 FRED/ALFRED series across output, labor, prices,
inflation expectations, rates, the yield curve, central-bank liquidity, credit
spreads, financial conditions, market stress, external balance, fiscal debt,
equities, and energy.

Supported unary transforms are level, difference, percent change, YoY, QoQ,
three/six-month annualized change, moving average, rolling percentile, and
rolling z-score. The library also exposes aligned spread, inversion, real-rate,
and ratio operations. Every operation uses only the current or previous values.

## Component score

For each transformed series:

1. calculate its rolling empirical percentile from available history;
2. map percentile `p` to `2p - 1`;
3. multiply by the catalog orientation;
4. clamp the result to `[-1, 1]`.

The current state score is the base-weighted mean of usable component scores.
If no component has sufficient history, the state score is `null` and the label
is `insufficient_data`.

## Confidence

Confidence is bounded to `[0, 1]` and combines:

- coverage: usable component weight divided by configured weight;
- freshness: exponential half-life decay from each component's availability
  time.

The formula is `coverage × (0.45 + 0.55 × average_freshness)`. Scores are not
suppressed solely for low confidence; the API and UI carry the confidence,
missing-series list, staleness flag, and as-of date so the user can judge them.

## Labels and trend

| Score | Label |
| --- | --- |
| `>= 0.60` | high |
| `>= 0.20` | elevated |
| `(-0.20, 0.20)` | neutral |
| `> -0.60` | soft |
| `<= -0.60` | low |

Trend compares the aggregate with the previous usable component readings:
rising above `+0.04`, falling below `-0.04`, otherwise stable.

Top drivers are the three largest absolute weighted contributions. No generated
narrative is required to explain a score.

## Eight dimensions

- Growth: output, production, payrolls, unemployment, claims, consumption,
  yield curve, and limited market context.
- Inflation: CPI/PCE headline and core, breakevens, and energy-price pressure.
- Liquidity: Federal Reserve assets, Treasury cash, reverse repo, and M2.
- Credit: high-yield/investment-grade spreads and financial conditions.
- Policy Tightness: administered/overnight rates and nominal/real Treasury
  yields.
- Risk: volatility and broad financial-stress/conditions indexes.
- Fiscal: federal debt relative to GDP; experimental.
- External: broad dollar and trade balance; experimental.

Positive-score meaning is dimension-specific and defined in
`data/macro/states.yaml`.

## Regime and changes

The regime view plots current Growth on the horizontal axis and Inflation on
the vertical axis, plus six monthly point-in-time recalculations.

Top Changes may include scheduled releases, vintage revisions, extreme state
scores, and stale-data warnings. Each item provides type, explanation,
previous/current value when available, date, state, importance, and source.
