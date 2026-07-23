# World Explainer product direction

## North star

World State Terminal is a daily, evidence-grounded explanation of how the world
works through financial markets:

> Open the terminal and understand today's world in ten minutes: what happened,
> why it matters, how it transmits, what markets confirm, what remains unknown,
> and what to learn next.

It is not a trading-signal terminal and not a wall of macro scores.

## Mature patterns adopted

The implementation borrows product patterns, not proprietary code:

- [Bloomberg Terminal News](https://professional.bloomberg.com/products/bloomberg-terminal/news/):
  top news, concise first-read framing, and news connected to market analytics.
- [Koyfin Market Dashboards](https://www.koyfin.com/features/market-dashboards/):
  one global multi-asset view before drilling into individual instruments.
- [OpenBB](https://github.com/OpenBB-finance/OpenBB):
  connect data once, expose it to dashboards and AI, and keep the workspace
  provider-neutral.
- [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT):
  separate data collection, data engineering, model tasks, and applications.
- [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot):
  deterministic numbers, LLM-assisted narrative, and provenance for every
  research output.
- [TradingAgents](https://github.com/TauricResearch/TradingAgents):
  provider routing and explicit debate/alternative hypotheses, without adopting
  its automated trading objective.
- [Perplexity](https://www.perplexity.ai/hub):
  cited answers and a follow-up path from a concise answer into deeper research.

## Product hierarchy

1. Today's five most important world events
2. Global market reaction across eleven selected assets
3. A pre-declared market hypothesis checked against observed asset directions
4. One retrieval-practice loop with answer reveal and a transfer question
5. An evidence-grounded AI tutor
6. Macro state data as a supporting layer, not the homepage

## Explanation contract

Every explanation must separate:

- **Fact:** timestamped source, release, speech, or price observation.
- **Expectation:** what changed relative to the market's prior view.
- **Hypothesis:** the proposed causal transmission chain.
- **Confirmation:** cross-asset evidence consistent with the hypothesis.
- **Alternative:** another plausible explanation.
- **Unknown:** data the system cannot observe, especially private order flow.
- **Confidence:** how much evidence supports the current interpretation.
- **Falsifier:** the observation that would weaken or reject the explanation.

The default reading sequence is deliberately shorter:

```text
surprise vs prior expectation
        → expectation being repriced
        → first pricing variable
        → confirming or contradicting assets
        → alternative explanation
        → falsifier
```

The interface does not display every available field at once. Source facts,
causal tests, and alternatives appear on demand; the homepage keeps only the
core question, leading hypothesis, and current market verdict.

## Learning contract

Reading an explanation is not the same as learning it. Each daily lesson uses:

1. a question the learner must judge before seeing the answer;
2. a worked causal chain revealed on demand;
3. immediate explanatory feedback;
4. a transfer question that applies the same method to another event.

The AI tutor follows the same sequence and must identify the expectation shift,
pricing variable, supporting and weakening evidence, alternative explanation,
and falsifier. For central-bank stories it must distinguish a pure policy shock
from information the central bank reveals about the economy.

The terminal never treats "buyers exceeded sellers" as a sufficient cause.
Algorithms, stop losses, dealer hedging, and liquidity can explain the speed or
amplitude of a move, while policy expectations and cross-asset repricing explain
why the move can persist.

## AI architecture

```text
Public news + official releases + market prices + macro database
                              |
                     deterministic evidence pack
                              |
        OpenAI Responses API / Ollama / compatible provider
                              |
       facts + inference + unknowns + citations + learning prompt
```

The server owns evidence construction and credentials. News text is treated as
untrusted data. The model cannot substitute invented facts for missing evidence.
With no model configured, deterministic teaching rules remain available.

## Non-goals

- high-frequency execution;
- definitive attribution to a specific institution without order-flow evidence;
- personalized investment recommendations;
- hidden confidence or unsupported certainty;
- dependence on a single model or data vendor.
