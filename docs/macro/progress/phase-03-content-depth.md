# Phase 3 causal learning and content depth

Status: complete on 2026-07-23.

## Problem

The redesigned workspace was visually usable, but the content still placed too
many summaries, scores, disclaimers, and explanations at the same level. It
described causal chains without letting the learner test them, and market cards
did not say whether current prices supported or weakened the lead hypothesis.

## Research translated into product rules

The implementation adopts public ideas, not proprietary content:

- The [Federal Reserve's research on monetary-policy shocks](https://www.federalreserve.gov/econres/feds/the-effect-of-the-federal-reserve-on-the-stock-market-magnitudes-channels-and-shocks.htm)
  separates pure policy shocks, central-bank information, yields, cash-flow
  expectations, and equity risk premia. Central-bank explanations now expose
  the information-effect alternative instead of treating every speech as a
  one-dimensional rate shock.
- The [Bank of England's transmission overview](https://www.bankofengland.co.uk/quarterly-bulletin/2024/2024/about-a-rate-of-general-interest-how-monetary-policy-transmits)
  moves from expected policy rates to financial conditions, then the real
  economy and inflation. The terminal now labels each stage of the chain.
- [BlackRock's market-driven scenario method](https://www.blackrock.com/aladdin/platforms/solutions/aladdin-wealth/making-of-a-market-driven-scenario)
  uses multiple plausible scenarios and explicit cross-variable shocks. Each
  event now includes confirmations, alternatives, and falsifiers.
- [Nielsen Norman Group's progressive-disclosure guidance](https://www.nngroup.com/articles/progressive-disclosure/)
  keeps essential information visible and advanced detail secondary. Event
  analysis and the macro-state foundation are closed until requested.
- [Retrieval Practice](https://www.retrievalpractice.org/summary) emphasizes
  retrieval, feedback, spacing, and transfer. The daily lesson now asks for a
  judgment before revealing the worked chain and answer.
- [Finimize's explanation workflow](https://finimize.com/business/resources/insights/why-should-i-care-how-finimize-produces-news)
  prioritizes what happened, why it matters, and what comes next. The terminal
  keeps the first read concise while moving depth into evidence tests.

## Delivered

- low-signal central-bank administrative stories are excluded;
- news ranking balances impact with hours since publication so a stale high-score
  headline does not automatically displace today's consequential event;
- repeated event mechanisms are deduplicated;
- event playbooks declare expectation shift, scenario, first pricing variables,
  expected directions, confirmations, alternatives, and falsifiers;
- the leading scenario is checked against observed cross-asset directions;
- market cards state the macro role of each instrument;
- the homepage removes event counts, market counts, impact scores, repeated
  confidence labels, and long footer/source disclaimers;
- expanded events show known fact, repricing hypothesis, labeled causal chain,
  supporting evidence, rejecting evidence, and alternative explanation;
- daily learning uses question-first retrieval, answer reveal, feedback, and a
  transfer prompt;
- the AI tutor follows the same evidence-and-falsification structure;
- the long-term macro-state strip is collapsed by default.

## Verification

- 35 Macro Engine tests pass at 88.42% coverage;
- Ruff and strict mypy pass;
- TypeScript, focused Biome, safe-HTML, and local-secret checks pass;
- Macro production build passes;
- live briefing returns five distinct event mechanisms, eleven markets, and a
  cross-asset verdict;
- desktop and phone browser layouts have no document-level horizontal overflow;
- event expansion and answer reveal are interactive.
