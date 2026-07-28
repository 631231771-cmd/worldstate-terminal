# Global research desk redesign

Status: implemented through Phase 9, reviewed 2026-07-28.

## Product decision

World State Terminal is not a news reader with market cards. It is a daily
research desk that answers four questions:

1. What changed relative to expectations?
2. Which pricing variable should react first?
3. Do independent assets confirm the same explanation?
4. What evidence would weaken or overturn it?

The previous single long page repeated the same lead story across hero, chain,
brief, validation, news, markets, and viewpoints. Phase 8 separates the product
into seven workspaces:

| Workspace | Question |
| --- | --- |
| 今日桌面 | What matters now, what is the next release, and what is the market pricing? |
| 事件雷达 | What is the complete shock-to-policy transmission chain? |
| 宏观日历 | What should be written down before an official release? |
| 资产地图 | Is the move one-day noise, a trend, a confirmation, or a divergence? |
| 国家与主题 | Which persistent macro theme and region does today's evidence belong to? |
| 观点与证据 | Which source calls succeeded, and which external views are actually relevant? |
| 学习与复盘 | Which reusable event playbook helps transfer today's lesson? |

## Mature-product patterns used

- [Koyfin Global Economics](https://www.koyfin.com/data-coverage/economics/)
  informed country and global-yield orientation. The implementation is
  original and uses the terminal's own evidence model.
- [TradingView Economic Calendar](https://www.tradingview.com/economic-calendar/)
  informed date, country, importance, and event-category organization.
- [Macrobond](https://www.macrobond.com/) informed the emphasis on source
  lineage, revision awareness, and combining data with research context.
- [Bloomberg Terminal](https://www.bloomberg.com/professional/products/bloomberg-terminal/)
  informed the idea of one operating desk across news, data, markets, and
  research rather than independent widgets.
- [CRATES](https://github.com/DocAMYMEI/CRATES) and open macro dashboards were
  reviewed for event-window, cross-asset, regime, and correlation workflows.
  No upstream code was copied or vendored.

## Evidence model

### Facts

Event facts come from bounded public feeds. Official schedules prefer BLS,
BEA, Federal Reserve, ECB, Bank of England, and Bank of Japan first-party
pages. Calendar rows reveal whether they were read live or came from an
explicitly dated official annual schedule.

### Prices

Twelve core assets retain up to thirty recent daily observations. The desk
derives:

- 1-, 5-, and 20-session changes;
- global equity breadth;
- market-implied growth, inflation, liquidity, and risk-appetite states;
- selected rolling pair relationships;
- explicit confirmation and divergence patterns.

These are descriptive indicators. Correlation does not establish causality,
and daily closing data cannot identify a specific fund order or keyword
algorithm.

### Viewpoints

Institutional, researcher, practitioner, and X content is always an external
hypothesis. Every row receives:

- a relevance score against the lead event;
- the matched mechanism or a background label;
- variables that could test it;
- a source-class caveat.

The deep brief excludes viewpoints below the mechanism-relevance threshold, so
an interesting but unrelated post no longer appears beside the main event.

### AI

The tutor evidence pack includes events, official calendar, market state,
cross-asset patterns, topics, countries, viewpoints, source operations, and
limitations. The deterministic no-key tutor can answer calendar and
relationship questions. Configured models receive the same bounded server
evidence rather than unrestricted page text.

## Deliberate limits

- Free upstreams can be delayed or unavailable.
- Yahoo daily prices are not institutional tick data or order flow.
- A calendar time can change; users should open the linked official source
  before a high-impact event.
- Market-implied regimes describe the current tape and can conflict with
  slower economic data.
- Country attention is an evidence-priority score, not a risk rating.
- This is an educational research system, not investment advice.

## Phase 9: event reaction workbench

The macro calendar is now an event research workbench rather than a schedule
alone. It uses the same six-step path before and after a release:

1. What happened?
2. What changed relative to expectations?
3. Which variables priced first?
4. Why did individual assets react differently?
5. Which market mechanisms may have amplified the move?
6. What should confirm or falsify the explanation next?

Before a release, the workbench labels the analysis as a scenario plan and
does not fabricate Actual, Forecast, or Prior values. After a release, the
same structure becomes a reaction review when verified values are available.
Daily public prices are labelled as context rather than precise minute-window
event returns.

Silver is now a first-class market alongside gold. Its explanation explicitly
separates the precious-metal channel from industrial demand, and the
cross-asset system includes gold/silver confirmation. U.S. Census durable-goods
releases are also included from the first-party schedule, bringing the official
calendar ledger to seven source families.

The design deliberately treats keyword algorithms, stop-losses, CTA activity,
options hedging, and crypto liquidations as possible amplifiers. They are not
presented as the root cause or as observed private fund orders without direct
evidence.
