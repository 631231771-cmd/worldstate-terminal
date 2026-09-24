import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../../api/client";
import { TimeSeriesChart, type ChartHorizon } from "../../components/TimeSeriesChart";
import type { ReleaseSummary } from "../../types";
import type { DisplayQuote, LiveGcResponse, OfficialHeadline, ProductMarketItem, WorkbenchFactor } from "../../types/product";
import { eventName, eventTime, recentEvents, upcomingEvents } from "./RadarWorkspace";
import { focusMarkets, marketRole, ROLE_LABELS, type MarketRole } from "./marketContext";

const ORDER: MarketRole[] = ["gold", "oil", "nasdaq", "rates10", "dollar", "btc", "silver", "equity", "rates2", "real", "vix", "credit"];
const QUOTE_KEYS: Partial<Record<MarketRole, string>> = {
  gold: "xau_usd", silver: "xag_usd", oil: "cl_quote", nasdaq: "nq_quote",
  rates10: "us10y_quote", dollar: "dxy_quote", btc: "btc_quote", equity: "es_quote",
};
const RELATED: Partial<Record<MarketRole, MarketRole[]>> = {
  gold: ["rates10", "real", "dollar", "silver", "nasdaq"],
  oil: ["dollar", "rates10", "gold", "equity"],
  nasdaq: ["rates10", "real", "dollar", "equity", "vix"],
  rates10: ["real", "dollar", "gold", "nasdaq"],
  dollar: ["rates10", "gold", "oil", "nasdaq"],
};

function stamp(value: string | null | undefined) {
  if (!value || Number.isNaN(Date.parse(value))) return "时间未记录";
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
function liveStamp(value: string | null | undefined) {
  if (!value || Number.isNaN(Date.parse(value))) return "—";
  return new Date(value).toLocaleTimeString("zh-CN", {hour12:false,hour:"2-digit",minute:"2-digit",second:"2-digit"});
}
function number(value: number | null | undefined, digits = 2) {
  return value == null ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}
function move(value: number | null | undefined, unit: string) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)} ${unit}`;
}
function quoteStatus(q: DisplayQuote, now: number) {
  if (q.price == null) return "暂不可用";
  if (q.status === "stale" || q.error || !q.quoted_at || now - Date.parse(q.quoted_at) > (q.status === "live" ? 30_000 : ((q.delay_minutes ?? 0) * 60 + 300) * 1000)) return "旧报价";
  if (q.status === "live") return "ATAS 本机实时 · 仅展示";
  return q.delay_minutes ? `约延迟 ${q.delay_minutes} 分钟` : "参考价 · 延迟未承诺";
}
function factorFrequency(value: string | null) {
  return ({ daily: "日频", weekly: "周频", monthly: "月频", quarterly: "季频" } as Record<string, string>)[value ?? ""] ?? "频率未记录";
}
function factorUnit(value: string | null) {
  return ({ percent: "%", index: "指数点", million_barrels: "百万桶", thousand_barrels_per_day: "千桶/日", billions_usd: "十亿美元" } as Record<string, string>)[value ?? ""] ?? (value ?? "");
}
function factorAge(item: WorkbenchFactor) {
  if (!item.period) return "";
  const days = (Date.now() - Date.parse(item.period)) / 86400_000;
  const limit = item.frequency === "weekly" ? 10 : item.frequency === "monthly" ? 45 : 5;
  return days > limit ? " · 较旧" : "";
}
function roleTopic(role: MarketRole) { return role === "oil" ? "energy" : "policy"; }

export function MarketDeskWorkspace({ markets, events, onEvent, onData, advanced }: {
  markets: ProductMarketItem[]; events: ReleaseSummary[];
  onEvent: (id: string) => void; onData: () => void; advanced: boolean;
}) {
  const [selected, setSelected] = useState<MarketRole>(() => {
    const saved = localStorage.getItem("worldstate.workbench.asset") as MarketRole | null;
    return saved && ORDER.includes(saved) ? saved : "gold";
  });
  const [quotes, setQuotes] = useState<DisplayQuote[]>([]);
  const [liveGc, setLiveGc] = useState<LiveGcResponse | null>(null);
  const [quoteError, setQuoteError] = useState(false);
  const [headlines, setHeadlines] = useState<OfficialHeadline[]>([]);
  const [newsScope, setNewsScope] = useState("");
  const [newsError, setNewsError] = useState(false);
  const [factorResult, setFactorResult] = useState<{asset:string;items:WorkbenchFactor[]}|null>(null);
  const [factorError, setFactorError] = useState(false);
  const [horizon, setHorizon] = useState<ChartHorizon>("1m");
  const [now, setNow] = useState(Date.now());
  const [refreshKey, refresh] = useState(0);

  useEffect(() => {
    let active = true;
    const load = () => void api.productQuotes().then(data => { if (active) { setQuotes(data.items); setQuoteError(false); } }).catch(() => { if (active) setQuoteError(true); });
    load();
    const timer = window.setInterval(load, 60_000);
    const clock = window.setInterval(() => setNow(Date.now()), 30_000);
    const visible = () => { if (!document.hidden) load(); };
    document.addEventListener("visibilitychange", visible);
    return () => { active = false; clearInterval(timer); clearInterval(clock); document.removeEventListener("visibilitychange", visible); };
  }, [refreshKey]);
  useEffect(() => {
    let active = true;
    const load = () => void api.productLiveGc().then(data => { if (active) setLiveGc(data); }).catch(() => { if (active) setLiveGc(null); });
    load();
    const timer = window.setInterval(load, 2000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  useEffect(() => {
    let active = true;
    const load = () => void api.productHeadlines().then(data => { if (active) { setHeadlines(data.items); setNewsScope(data.source_scope); setNewsError(false); } }).catch(() => { if (active) setNewsError(true); });
    load(); const timer = window.setInterval(load, 900_000);
    return () => { active = false; clearInterval(timer); };
  }, [refreshKey]);
  useEffect(() => {
    let active = true; setFactorError(false);
    void api.productFactors(selected).then(data => { if (active) setFactorResult({asset:selected,items:data.items}); }).catch(() => { if (active) setFactorError(true); });
    return () => { active = false; };
  }, [selected, refreshKey]);
  // Display cached observations immediately. The existing official sync has a durable
  // six-hour provider cache and does not block the workbench or turn old rows into PIT.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api.syncReasoningEvidence().then(() => refresh(value => value + 1)).catch(() => undefined);
    }, 2500);
    return () => clearTimeout(timer);
  }, []);

  const daily = useMemo(() => new Map(focusMarkets(markets).map(item => [marketRole(item)!, item])), [markets]);
  const quoteMap = useMemo(() => new Map(quotes.map(item => [item.key, item])), [quotes]);
  const display = (role: MarketRole) => {
    const live = role === "gold" && liveGc?.enabled && liveGc.quote?.status === "live" && quoteStatus(liveGc.quote, now) !== "旧报价" ? liveGc.quote : null;
    const q = quoteMap.get(QUOTE_KEYS[role] ?? "");
    const day = daily.get(role);
    const currentQuote = q?.price != null && quoteStatus(q, now) !== "旧报价";
    return { q: live ?? (currentQuote || !day ? q : undefined), day };
  };
  const choose = (role: MarketRole) => { setSelected(role); localStorage.setItem("worldstate.workbench.asset", role); };
  const active = display(selected);
  const latest = active.q?.price ?? active.day?.value ?? null;
  const latestUnit = active.q?.unit ?? (["rates2", "rates10", "real", "credit"].includes(selected) ? "%" : selected === "gold" || selected === "silver" ? "USD/盎司" : selected === "oil" ? "USD/桶" : "");
  const activeChange = active.q ? active.q.change : active.day?.change;
  const activeChangeUnit = active.q?.change_unit ?? active.day?.change_unit ?? "%";
  const chart = active.q?.points && active.q.points.length > 1 ? active.q.points : active.day?.chart_points ?? [];
  const intraday = Boolean(active.q?.points && active.q.points.length > 1);
  const chartLabel = intraday
    ? active.q?.status === "live" ? `${active.q.symbol} · 本次 ATAS 连接以来的 1 分钟图，不进入事件研究` : `${active.q?.label ?? ROLE_LABELS[selected]} · 公开分钟参考图，不进入事件研究`
    : active.day
      ? `${active.day.label}${active.day.symbol ? ` (${active.day.symbol})` : ""} · 日频历史${active.q ? "；与上方参考报价来源/合约不同" : ""}`
      : "暂无可用图表";
  const selectedTopic = roleTopic(selected);
  const relevantNews = headlines.filter(item => item.topic === selectedTopic).slice(0, 4);
  const latestNews = headlines.slice(0, 5);
  const agenda = upcomingEvents(events).slice(0, 5);
  const recent = recentEvents(events).slice(0, 2);
  const related = (RELATED[selected] ?? ["rates10", "dollar", "gold", "oil"]).filter(role => role !== selected);
  const factors = factorResult?.asset === selected ? factorResult.items : [];

  return <div class="market-desk" aria-label="市场信息工作台">
    <div class="desk-intro"><div><span class="desk-kicker">WORLDSTATE / MARKET DESK</span><h1>市场信息工作台</h1><p>选一个市场，同时看价格、相关数据、官方信息和下一场事件。</p></div><div class="desk-intro__actions"><span>{new Date(now).toLocaleDateString("zh-CN", {month:"long",day:"numeric",weekday:"long"})}</span><button type="button" onClick={() => refresh(value => value + 1)}>更新信息 ↻</button></div></div>
    <div class="desk-grid">
      <aside class="desk-watch" aria-label="自选市场"><div class="desk-pane-head"><h2>自选市场</h2><span>报价 / 最近有效记录</span></div>
        <div class="desk-watch__rows">{ORDER.filter(role => display(role).q || display(role).day).map(role => {
          const {q,day} = display(role); const chosen = selected === role;
          const value = q?.price ?? day?.value ?? null;
          const change = q ? q.change : day?.change ?? null;
          const unit = q?.change_unit ?? day?.change_unit ?? "%";
          return <button key={role} type="button" class={chosen ? "desk-asset desk-asset--active" : "desk-asset"} onClick={() => choose(role)} aria-pressed={chosen}>
            <span class="desk-asset__name">{ROLE_LABELS[role]}<small>{q ? quoteStatus(q, now) : `${day?.details.granularity_seconds === 86400 ? "日频" : "最近记录"} · ${day?.details.timestamp?.slice(0,10) ?? "时间未知"}`}</small></span>
            <span class="desk-asset__reading"><strong>{number(value, role === "rates10" ? 3 : 2)}</strong><small class={change != null && change < 0 ? "desk-down" : "desk-up"}>{move(change,unit)}</small></span>
          </button>;
        })}</div>
        {quoteError ? <p class="desk-soft-error">报价暂时无法更新，保留最近结果。</p> : null}
      </aside>
      <div class="desk-main">
        <section class="desk-focus" aria-label={`${ROLE_LABELS[selected]}详情`}><div class="desk-focus__top"><div><span class="desk-kicker">SELECTED MARKET</span><h2>{ROLE_LABELS[selected]}<small>{active.q?.symbol ?? active.day?.symbol ?? ""}</small></h2></div><div class="desk-focus__number"><strong>{number(latest, selected === "rates10" ? 3 : 2)}<small>{latestUnit}</small></strong><span class={(activeChange ?? 0) < 0 ? "desk-down" : "desk-up"}>{move(activeChange, activeChangeUnit)}</span></div></div>
          <div class="desk-source-line"><span>{active.q ? quoteStatus(active.q,now) : active.day ? "日频市场记录" : "暂无报价"}</span><span>记录时间 {stamp(active.q?.quoted_at ?? active.day?.details.timestamp)}</span>{active.q?.error ? <span>来源暂不可用</span> : null}</div>
          {selected === "gold" && liveGc?.enabled ? <div class="desk-live-strip">{active.q?.status === "live" ? <><span>GC {active.q.contract_code}{active.q.exchange ? ` · ${active.q.exchange}` : ""}{active.q.source_symbol?.startsWith("#") ? " · ATAS 连续图当前合约" : ""}</span><span>买 {number(active.q.best_bid)} / 卖 {number(active.q.best_ask)} · 最近成交量 {number(active.q.last_trade_volume,0)}</span><span>事件 {liveStamp(active.q.event_at)} · 接收 {liveStamp(active.q.received_at)}</span><span>1 分钟 O {number(active.q.bar_1m?.open)} · H {number(active.q.bar_1m?.high)} · L {number(active.q.bar_1m?.low)} · C {number(active.q.bar_1m?.close)} · V {number(active.q.bar_1m?.volume,0)}</span></> : <span>GC 本机行情未连接或已断开；上方为其他来源的参考价。</span>}</div> : null}
          {chart.length > 1 ? <><div class="desk-chart-switch">{(["1w","1m","3m","1y"] as ChartHorizon[]).map(item => <button key={item} type="button" class={horizon === item ? "active" : ""} onClick={() => setHorizon(item)}>{item.toUpperCase()}</button>)}</div><p class="desk-chart-basis">{chartLabel}</p><TimeSeriesChart points={chart} horizon={horizon} intraday={intraday} height={220}/></> : <div class="desk-chart-empty">暂无可用走势；不补画不存在的历史。<button type="button" onClick={onData}>查看数据来源 →</button></div>}
          <div class="desk-related"><div class="desk-pane-head"><h3>相关市场</h3><span>仅作并列观察，不推断因果</span></div><div>{related.map(role => { const {q,day} = display(role); return <button type="button" key={role} onClick={() => choose(role)}><span>{ROLE_LABELS[role]}</span><strong>{number(q?.price ?? day?.value, role === "rates10" || role === "real" ? 3 : 2)}</strong><small>{q ? quoteStatus(q,now) : day ? "日频" : "缺失"}</small></button>; })}</div></div>
        </section>
        <section class="desk-factors"><div class="desk-pane-head"><h2>{selected === "oil" ? "库存与供需" : selected === "gold" || selected === "silver" ? "利率、美元与通胀" : "相关宏观因素"}</h2><span>已观察数据 · 不代表涨跌原因</span></div><div class="desk-factor-grid">{factors.map(item => <div class="desk-factor" key={item.series_key}><span>{item.label}{item.proxy ? " · 代理" : ""}</span><strong>{number(item.value,3)} <small>{factorUnit(item.unit)}</small></strong><small>{item.observed ? `${factorFrequency(item.frequency)} · ${item.period ?? ""}${factorAge(item)}` : "本地尚无记录"}</small>{advanced && item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">官方来源 ↗</a> : null}</div>)}{factorError ? <p class="desk-soft-error">宏观因素暂时无法读取。</p> : null}{!factors.length && !factorError ? <p class="desk-wait">正在读取已有官方数据…</p> : null}</div></section>
        <section class="desk-related-news"><div class="desk-pane-head"><h2>{ROLE_LABELS[selected]}相关信息</h2><span>{selectedTopic === "energy" ? "EIA · 能源" : "美联储 · 政策"}</span></div>{relevantNews.length ? relevantNews.map(item => <a key={item.url} href={item.url} target="_blank" rel="noreferrer"><time>{stamp(item.published_at)}</time><strong>{item.title}</strong><small>{item.source} ↗</small></a>) : <p class="desk-wait">暂无该主题的官方消息；消息并不等于价格原因。</p>}</section>
      </div>
      <aside class="desk-rail"><section><div class="desk-pane-head"><h2>最新金融信息</h2><span>官方公开来源</span></div><div class="desk-news">{latestNews.length ? latestNews.map(item => <a key={item.url} href={item.url} target="_blank" rel="noreferrer"><span>{item.source} · {stamp(item.published_at)}</span><strong>{item.title}</strong></a>) : <p class="desk-wait">{newsError ? "官方消息暂时无法更新。" : "正在读取官方消息…"}</p>}</div>{newsScope ? <small class="desk-scope">{newsScope}</small> : null}</section>
      <section><div class="desk-pane-head"><h2>接下来</h2><span>本机时间</span></div>{agenda.length ? agenda.map(event => <button type="button" class="desk-event" key={event.id} onClick={() => onEvent(event.id)}><time>{eventTime(event.scheduled_at)}</time><strong>{eventName(event)}</strong><small>{event.period_label} · 查看预期 →</small></button>) : <div class="desk-wait">本地暂无未来事件。<button type="button" onClick={onData}>检查官方日历 →</button></div>}{recent.length ? <div class="desk-recent"><h3>最近发布</h3>{recent.map(event => <button type="button" key={event.id} onClick={() => onEvent(event.id)}>{eventName(event)} <small>{event.period_label} →</small></button>)}</div> : null}</section></aside>
    </div>
    {advanced ? <div class="desk-method">报价仅供市场观察，不作为分钟事件研究输入；宏观因素来自已保存的 observed 观测，非完整历史首发版本。当前未提供完整市场新闻流，新闻标题与价格变动不构成因果证明。</div> : null}
  </div>;
}
