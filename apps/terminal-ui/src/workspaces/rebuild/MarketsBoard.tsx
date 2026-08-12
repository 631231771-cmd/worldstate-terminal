import { useMemo, useState } from "preact/hooks";
import type { ProductMarketItem } from "../../types/product";
import { Badge, Panel, Sparkline, StateMessage } from "../../components/Primitives";

const TABS = ["All", "Rates", "FX", "Equities", "Commodities", "Risk"] as const;
type Horizon = "1d" | "1w" | "1m" | "3m";
const HORIZONS: Horizon[] = ["1d", "1w", "1m", "3m"];
const TAB_LABELS: Record<(typeof TABS)[number], string> = { All: "全部", Rates: "利率", FX: "外汇", Equities: "股票", Commodities: "商品", Risk: "风险 / 信用" };

function freshnessLabel(value: string): string {
  if (value === "STALE") return "数据较旧";
  if (value === "MISSING") return "缺失";
  return value;
}

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
    <td>{item.status !== "available" || item.freshness !== "AVAILABLE" ? <span class={`status-dot status-dot--${item.status}`}>{item.status === "missing" ? "缺失" : freshnessLabel(item.freshness)}</span> : item.derived ? <span class="status-dot">派生</span> : null}</td>
  </tr>;
}

export function MarketsBoard({ items, onOpen }: { items: ProductMarketItem[]; onOpen: (item: ProductMarketItem) => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("All");
  const filtered = useMemo(() => tab === "All" ? items : items.filter((item) => group(item) === tab), [items, tab]);
  if (!items.length) return <StateMessage title="暂无市场数据" detail="当前没有满足产品视图要求的 observed 日线行情。" action={<button type="button" class="button-primary">打开数据源</button>} />;
  return <div class="workspace workspace--product">
    <section class="page-heading page-heading--compact"><div><div class="eyebrow">MARKETS / DAILY CONTEXT</div><h1>市场</h1><p>最近有效交易观测的 1日、1周、1月和3月变化；利率与利差使用 bp，其余资产使用百分比。</p></div><div class="page-heading__aside"><Badge tone="good">{items.length} 项资产</Badge></div></section>
    <div class="tabs-bar">{TABS.map((item) => <button type="button" class={tab === item ? "active" : ""} onClick={() => setTab(item)} key={item}>{TAB_LABELS[item]}</button>)}</div>
    <Panel title="跨资产市场板" eyebrow={TAB_LABELS[tab]}><div class="table-wrap"><table class="market-board market-board--wide"><thead><tr><th>资产</th><th>最新</th><th>1日</th><th>1周</th><th>1月</th><th>3月</th><th>趋势</th><th></th></tr></thead><tbody>{filtered.map((item) => <MarketRow item={item} key={item.key} onOpen={onOpen} />)}</tbody></table></div>{!filtered.length ? <div class="empty-action"><div><h3>该分组暂无 observed 数据</h3><p>系统不会用 Fixture 填满这个页面。</p></div></div> : null}<p class="market-board__footnote">点击资产可查看图表与数据详情。这里是日线环境，不代替事件发布后的分钟反应。</p></Panel>
  </div>;
}
