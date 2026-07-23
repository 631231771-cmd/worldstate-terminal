---
project: World State Terminal
checkpoint: phase-3-causal-learning-complete
date: 2026-07-23
branch: feature/world-state-terminal
formal_commit: 6fb2760fc7b653b31b62597d559f6863d0a3c4b8
resume_from: phase-4-source-expansion-and-personal-learning-memory
---

# Phase 3 causal learning complete

> [!success] Stable resume point
> The terminal now teaches a falsifiable way to read macro news. Preserve the
> sequence: expectation shift → pricing variable → cross-asset validation →
> alternative explanation → falsifier.

## What changed

- News ranking balances impact with time since publication.
- Administrative central-bank headlines are filtered out.
- Repeated event mechanisms are deduplicated.
- Event playbooks declare scenarios, expected asset directions,
  confirmations, alternatives, and falsifiers.
- The lead hypothesis is compared with actual market directions.
- Market cards state what macro question each instrument helps answer.
- Expanded events separate known fact, repricing hypothesis, causal chain,
  support, rejection, and alternative explanations.
- The daily lesson asks the learner to judge first, then reveals a worked chain
  and feedback, followed by a transfer question.
- The AI tutor uses the same expectation/validation/falsification structure.
- Repeated counts, impact scores, confidence labels, and long disclaimers were
  removed from the first-read interface.
- The long-term macro state strip is collapsed by default.

## Research foundations

- Federal Reserve: pure policy shock versus central-bank information.
- Bank of England: policy expectations to financial conditions to the real
  economy and inflation.
- BlackRock: explicit multi-variable scenarios and alternatives.
- Nielsen Norman Group: progressive disclosure and lower cognitive load.
- Retrieval Practice: question-first retrieval, feedback, and transfer.
- Finimize: concise first read with depth available on demand.

The direct references are stored in
`docs/macro/progress/phase-03-content-depth.md`.

## Verification

- 35 Macro Engine tests pass at 88.39% coverage.
- Ruff, strict mypy, TypeScript, Biome, safe-HTML, and secret checks pass.
- Macro production build passes.
- Live API returns five current event mechanisms, eleven markets, and a lead
  cross-asset verdict.
- Desktop and 390 px phone layouts have no document-level horizontal overflow.
- Event expansion and the learning answer reveal both work.

## Services

The launcher-managed API and web interface were restarted after the changes and
left running on ports 8000 and 4173.

## Next work

Prioritize higher-quality multilingual sources, intraday event windows, and
personal learning memory. The next learning feature should remember concepts the
user has answered, revisit them with spacing, and distinguish “read” from
“retrieved correctly.”
