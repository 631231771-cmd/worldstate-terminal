import { useMemo, useState } from "preact/hooks";
import type { ProductMarketItem } from "../../types/product";
import { Badge, DetailsDisclosure, Panel, Sparkline, StateMessage } from "../../components/Primitives";

const TABS = ["All", "Rates", "FX", "Equities", "Commodities", "Risk"] as const;
type Horizon = "1d" | "1w" | "1m" | "3m";
const HORIZONS: Horizon[] = ["1d", "1w", "1m", "3m"];

function group(item: ProductMarketItem): string {
  if (item.asset_class === "rates") return "Rates";
  if (item.asset_class === "fx") return "FX";
  if (item.asset_class === "equity_index") return "Equities";
  if (item.asset_class === "metals" || item.asset_class === "energy") return "Commodities";
  return "Risk";
}

function formatHorizon(item: ProductMarketItem, horizon: Horizon): string {
  const point = item.horizons?.[horizon];
  const value = point?.value;
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} ${point?.unit ?? item.change_unit}`;
}

function MarketRow({ item, onOpen }: { item: ProductMarketItem; onOpen: (item: ProductMarketItem) => void }) {
  const direction = item.direction === "up" ? "up" : item.direction === "down" ? "down" : "neutral";
  return <tr class="market-row" onClick={() => onOpen(item)}>
    <td><div class="market-row__name"><strong>{item.label}</strong></div></td>
    <td class="market-row__value">{item.formatted_value}</td>
    {HORIZONS.map((horizon) => { const value = item.horizons?.[horizon]?.value; return <td class={`market-row__change ${value != null && value < 0 ? "negative" : value != null ? "positive" : ""}`} key={horizon}>{formatHorizon(item, horizon)}</td>; })}
    <td><Sparkline values={item.sparkline} tone={direction} /></td>
    <td>{item.status !== "available" || item.freshness !== "AVAILABLE" ? <span class={`status-dot status-dot--${item.status}`}>{item.status === "missing" ? "Missing" : item.freshness}</span> : null}</td>
  </tr>;
}

export function MarketsBoard({ items, onOpen }: { items: ProductMarketItem[]; onOpen: (item: ProductMarketItem) => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("All");
  const filtered = useMemo(() => tab === "All" ? items : items.filter((item) => group(item) === tab), [items, tab]);
  if (!items.length) return <StateMessage title="No market data" detail="No observed daily market data satisfies the current product view." action={<button type="button" class="button-primary">Open Data Sources</button>} />;
  return <div class="workspace workspace--product">
    <section class="page-heading page-heading--compact"><div><div class="eyebrow">MARKETS / DAILY CONTEXT</div><h1>Markets</h1><p>Latest valid observations across 1D, 1W, 1M and 3M horizons. Rates use bp; other assets use percent.</p></div><div class="page-heading__aside"><Badge tone="good">{items.length} assets</Badge></div></section>
    <div class="tabs-bar">{TABS.map((item) => <button type="button" class={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    <Panel title="Cross-asset board" eyebrow={tab.toUpperCase()}><div class="table-wrap"><table class="market-board market-board--wide"><thead><tr><th>Asset</th><th>Last</th><th>1D</th><th>1W</th><th>1M</th><th>3M</th><th>Trend</th><th></th></tr></thead><tbody>{filtered.map((item) => <MarketRow item={item} key={item.key} onOpen={onOpen} />)}</tbody></table></div>{!filtered.length ? <div class="empty-action"><div><h3>No observed data in this group</h3><p>Do not fill this view with fixture values.</p></div></div> : null}</Panel>
    <Panel title="Reading notes" eyebrow="RESEARCH NOTE"><ul class="boundary-list"><li>Market direction describes price movement, not good or bad.</li><li>Provider, PIT, and quality details are progressively disclosed.</li><li>Daily context cannot replace minute event reaction data.</li></ul><DetailsDisclosure label="Capability boundary"><p class="method-note">Event research is enabled only when capability inventory reports eligible intraday data.</p></DetailsDisclosure></Panel>
  </div>;
}
