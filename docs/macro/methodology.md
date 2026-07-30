# Macro-event methodology

An analysis run is reproducible from four point-in-time inputs: the release
bundle, pre-event consensus snapshots, market bars available for the selected
stages, and the regime snapshot known at T0.

The pipeline is:

1. Validate source and availability timestamps.
2. Compute indicator-level raw, relative and standardized surprise.
3. Classify the bundle (for example, broad hot CPI or a headline/core conflict).
4. Calculate stage-relative market windows.
5. Detect volatility-adjusted earliest observed reactions and reversals.
6. Match history using a fixed recipe selected before viewing the outcome.
7. Score several competing macro transmission hypotheses.
8. Build an EvidencePack and optionally ask AI to turn it into readable prose.

Confidence falls with contaminated windows, missing benchmark assets, proxy or
coarse-grained data, low historical sample size and cross-asset disagreement.
The output never asserts that a single rule or participant caused the move.
