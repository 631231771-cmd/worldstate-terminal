# Macro Reasoning Engine v1

Updated: 2026-09-21

This checkpoint implements one usable source-to-evidence slice. It does not
attempt Scenario versioning, analogue research, forecast scoring, or automated
news ingestion.

## Domain boundary

The workflow is deliberately separated into three kinds of statements:

1. `ResearchSource` stores the supplied material, author, URL, retrieval time,
   content hash, and capture provenance.
2. `AuthorClaim` stores an exact quote and a candidate interpretation. A claim
   remains `draft` until a local user explicitly confirms or rejects it.
3. `MechanismAssessment` stores the deterministic WorldState check. It never
   rewrites the source or claim and never labels agreement as causal proof.

The first versioned playbook is bundled at
`worldstate/reasoning/playbooks/macro_reasoning_v1.yaml`. Pydantic rejects
unknown fields, invalid targets, duplicate mechanisms, and missing competitor
references. The generic WorldState playbook contains:

- energy supply shock;
- demand acceleration;
- dollar/liquidity easing.

It is not presented as a named external researcher's framework. A Liangyi or
other external playbook must be derived from an exact, traceable source before
being attributed to that author.

## Evidence evaluation

Each causal-chain step declares its evidence target, expected direction,
minimum absolute change, horizon, and maximum age. The evaluator reads only the
claim's own `data_mode` and uses existing point-in-time macro state plus market
bars available at the requested `as_of`.

Each check is one of:

- `supporting`: fresh data exceeds the threshold in the declared direction;
- `contradicting`: fresh data exceeds it in the opposite direction;
- `neutral`: data exists but does not cross the threshold;
- `missing`: the dataset is absent, stale, or lacks a comparable change;
- `mixed`: multiple checks inside one step conflict.

The output contains the chain progress, supporting evidence, contradicting
evidence, missing evidence, falsifiers, and limitations. It contains no
probability-like confidence number. Daily checks do not claim event-minute
ordering.

Every run persists the playbook version/hash, `as_of`, observed input snapshot,
input hash, structured result, and output hash. Repeating a run against the
same inputs and time produces the same hashes.

## API

- `GET /v2/reasoning/playbooks`
- `GET /v2/reasoning/cases?data_mode=observed`
- `POST /v2/reasoning/sources`
- `POST /v2/reasoning/sources/{source_id}/claims`
- `PATCH /v2/reasoning/claims/{claim_id}`
- `POST /v2/reasoning/claims/{claim_id}/assessments`

Writes keep the existing local/write-token boundary. Exact quotes must occur in
the saved source. AI extraction is accepted only with extractor-model
provenance; the current UI intentionally starts with manual extraction rather
than pretending an unavailable AI provider performed it.

## First observed case

The runtime database contains the user's example energy-supply-chain view as a
user-authored research note. The latest observed assessment on September 21
reported:

- energy supply shock: incomplete, consecutively supported through 1 of 6 steps;
- demand acceleration: unconfirmed, consecutively supported through 2 of 4 steps;
- dollar/liquidity easing: incomplete.

This is a time-specific output, not a permanent conclusion. Missing/stale
dollar and gold context prevented the system from completing those chains.

## Explicit next boundary

The next stage may add source-assisted AI candidate extraction and migrate more
of the legacy front-end teaching paths into YAML. Scenario trees, Thesis
versioning, historical analogues, Outcome tracking, and forecast track records
remain out of scope for this checkpoint.
