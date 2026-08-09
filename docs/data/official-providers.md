# Official macro providers

WorldState v0.5 uses official publishers as the authority for actual values and
revisions. The adapters are connected to append-only release/value, calendar,
quality, Provider-run and source-artifact persistence. Commands report partial
or blocked status when one upstream source is unavailable; they never replace
missing observed inputs with fixture data.

## BLS Public Data API

`BlsOfficialProvider` maps only the CPI and employment series needed by the
current product:

| WorldState indicator | BLS series | Source/derived semantics |
| --- | --- | --- |
| Headline CPI MoM / YoY | `CUSR0000SA0` | percent change derived from retained index levels |
| Core CPI MoM / YoY | `CUSR0000SA0L1E` | percent change derived from retained index levels |
| Nonfarm payrolls | `CES0000000001` | thousands of persons |
| Unemployment rate | `LNS14000000` | percent |
| Average hourly earnings MoM / YoY | `CES0500000003` | percent change derived from retained levels |
| Labor-force participation | `LNS11300000` | percent |

The adapter preserves source level/unit and marks derived values with their
method/source periods. It supports the smaller public request tier without an
API key and chunks long ranges; a registered key raises the documented limits.
It also parses official CPI and Employment Situation schedule pages in
`America/New_York` and emits a typed schema error if the expected structure
changes.

The live public tier can accept `calculations=true` while returning
`Calculations have been disabled for this request.` In that case WorldState does
not drop CPI or earnings: it calculates 1-month and 12-month percent changes
from the official retained levels, rounds to the one-decimal release convention,
and records `calculation_source=worldstate_from_official_levels`. When BLS does
return `pct_changes`, `calculation_source=bls_calculations` is retained instead.
The unmodified response bytes and their SHA-256 hash remain the SourceArtifact;
each normalized ReleaseValue links to that artifact and keeps the raw level,
raw unit, standardized unit and derivation method. Without a release-time value
inside the API response, acquisition time remains the conservative availability
proxy and the capture is quality B rather than being upgraded to a fabricated
historical first print.

The BLS Public Data API is **not a complete historical vintage archive**.
Today's response may contain revisions that were unknown at an old release.
WorldState must never label that response as an old first print. Repeated
retrievals can build an append-only local revision chain going forward; earlier
first-release fields remain missing unless a defensible vintage source exists.

Adapter mapping, disabled-calculation fallback, schedule parsing, public-range
chunking, revision semantics and point-in-time guards have deterministic tests.
The no-key Data API path was also smoke-tested with live responses for CPI and
employment. BLS public mode needs no key, but the official schedule HTML returned
HTTP 403 from the current validation network. That environmental access failure
is disclosed rather than treated as an empty or successful calendar. No full
observed historical backfill is claimed.

Official references:

- <https://www.bls.gov/developers/api_signature_v2.htm>
- <https://www.bls.gov/schedule/news_release/cpi.htm>
- <https://www.bls.gov/schedule/news_release/empsit.htm>

## Federal Reserve FOMC materials

`FederalReserveFomcProvider` reads 2015–2020 year-specific official archive pages
and the Board's current calendar for current/future meetings. It preserves
meeting boundaries (including unscheduled meetings) and official links for
statements, implementation notes, projections, press material and minutes.
Outputs retain source URL, publication/retrieval time and content hash. Unknown
page structures produce a typed error.

WorldState retains the research stages `statement`, `press_conference`,
`key_qa` and `press_end`, but stores an exact time only when an official source or
explicit verification record supports it. The adapter does not ask AI to invent
a key-Q&A time.

Future meetings are persisted before documents exist with scheduled statement
and press-conference stages. The exact `key_qa` and `press_end` times remain null
unless an official/verified record supplies them; no fixed duration is invented.
Calendar/material persistence is connected and the Federal Reserve public pages
were reachable in the current validation environment.

Official references:

- <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>
- <https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm>

## FRED and ALFRED

`FredAlfredProvider` supports FRED observations and ALFRED realtime periods or
explicit vintage dates. Its intended daily rate set includes DGS2, DGS10 and
DFII10; exact series used by a run must still be recorded in its manifest.

The adapter retains `realtime_start`, `realtime_end`, vintage date and source
artifact hash, and filters as-of queries so a future vintage cannot enter an old
information set. A FRED API key is required. Missing credentials return
`not_configured`; they never cause an observed run to consume fixtures.

The adapter has mocked point-in-time tests, but the current environment has no
FRED key and no live observed import is claimed.

Official references:

- <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- <https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html>

Public access does not imply unrestricted redistribution. Raw responses are
local provenance material and are not published as bulk datasets by WorldState.
