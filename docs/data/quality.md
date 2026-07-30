# Data quality

Every important input can record source name/URL, fetch time, availability time,
manual verification, fixture/proxy status, delay, granularity, missing reason
and quality grade.

Grades are evidence labels, not cosmetic badges:

- A: official or directly verified, point-in-time and fit for the method.
- B: reliable but delayed, manually verified or with a limited field gap.
- C: proxy/coarse/partially verified; useful only with visible caveats.
- D: fixture or materially incomplete; demonstration/case context only.
- unavailable: the calculation must not be emitted.

Contamination is stored separately because high-quality prices can still be a
poor basis for event attribution when another release or headline overlaps.
