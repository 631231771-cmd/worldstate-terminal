import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../api/client";
import { Badge, DetailsDisclosure, Drawer, Panel, StateMessage } from "../components/Primitives";
import { TimeSeriesChart, type ChartHorizon } from "../components/TimeSeriesChart";
import { WorkspaceBoundary } from "../components/WorkspaceBoundary";
import type { ReleaseSummary } from "../types";
import type { ProductCountry, ProductCountryDetail, ProductDimension, ProductEventDetail, ProductEventsResponse, ProductMarketItem, ProductMarketsResponse, ProductMacroResponse, ProductTodayResponse } from "../types/product";
import { DataControlWorkspace } from "../workspaces/data-control/DataControlWorkspace";
import { DataMethodsWorkspace } from "../workspaces/data-methods/DataMethodsWorkspace";
import { ResearchWorkspace } from "../workspaces/research/ResearchWorkspace";
import { EventsBoard } from "../workspaces/rebuild/EventsBoard";
import { MacroBoard } from "../workspaces/rebuild/MacroBoard";
import { MarketsBoard } from "../workspaces/rebuild/MarketsBoard";
import { TodayBoard } from "../workspaces/rebuild/TodayBoard";

type ProductView = "today" | "markets" | "macro" | "events" | "research" | "data-control" | "data-methods";
type SearchResult = { key: string; label: string; note: string; action: () => void };

const NAV = [
  { key: "today" as const, label: "Today", note: "当前环境" },
  { key: "markets" as const, label: "Markets", note: "跨资产市场" },
  { key: "macro" as const, label: "Macro", note: "全球宏观" },
  { key: "events" as const, label: "Events", note: "日历与研究" },
  { key: "research" as const, label: "Research", note: "判断与复盘" },
];

function routeState() {
  const [name, query = ""] = window.location.hash.replace(/^#/, "").split("?");
  const aliases: Record<string, ProductView> = { "cross-asset": "markets", "world-state": "macro", countries: "macro", series: "macro", "event-lab": "events", releases: "events", calendar: "events" };
  const accepted: ProductView[] = ["today", "markets", "macro", "events", "research", "data-control", "data-methods"];
  const routeName = name ?? "";
  return { view: accepted.includes(routeName as ProductView) ? routeName as ProductView : aliases[routeName] ?? "today", params: new URLSearchParams(query) };
}

function preferredRelease(items: ReleaseSummary[]): ReleaseSummary | null {
  const rank = (item: ReleaseSummary) => item.analysis_status === "completed" && item.reproducibility_status === "complete" ? 0 : item.status === "released" ? 1 : 2;
  return [...items].sort((a, b) => rank(a) - rank(b) || String(b.released_at ?? b.scheduled_at).localeCompare(String(a.released_at ?? a.scheduled_at)))[0] ?? null;
}

function CapabilityDetails({ capabilities, advanced }: { capabilities: Record<string, { available: boolean; status: string; reason: string | null }>; advanced: boolean }) {
  const labels: Record<string, string> = { CURRENT_STATE: "当前状态", MACRO_HISTORY: "宏观历史", POINT_IN_TIME: "PIT", EVENT_INTRADAY: "事件分钟", HISTORICAL_REPLAY: "历史回放", SURPRISE_ELIGIBLE: "惊喜计算" };
  return <dl class="detail-grid">{Object.entries(labels).map(([name, label]) => <div key={name}><dt>{label}</dt><dd>{capabilities[name]?.available ? "可用" : advanced ? capabilities[name]?.reason ?? "不可用" : "不可用"}</dd></div>)}</dl>;
}

function MarketDrawerContent({ item, advanced }: { item: ProductMarketItem; advanced: boolean }) {
  const [horizon, setHorizon] = useState<ChartHorizon>("1m");
  const horizons: ChartHorizon[] = ["1w", "1m", "3m", "1y"];
  return <>
    <div class="drawer-kpi"><strong>{item.formatted_value}</strong><Badge tone={item.direction === "down" ? "warn" : "info"}>{item.change == null ? "暂无变化" : `${item.change > 0 ? "+" : ""}${item.change.toFixed(2)} ${item.change_unit}`}</Badge></div>
    <Panel title="价格轨迹" eyebrow="CONTINUOUS OBSERVATIONS" aside={item.derived ? <Badge tone="info">派生序列</Badge> : null}>
      <div class="chart-horizons">{horizons.map((value) => <button type="button" class={horizon === value ? "active" : ""} onClick={() => setHorizon(value)} key={value}>{value.toUpperCase()}</button>)}</div>
      <TimeSeriesChart points={item.chart_points ?? []} horizon={horizon} />
      {item.details.continuity_status === "segmented" ? <p class="chart-warning">检测到不兼容的数据区段；图表和涨跌只使用最新连续区段。</p> : null}
    </Panel>
    <Panel title="研究关联" eyebrow="MACRO CONTEXT"><div class="context-links"><span>实际利率</span><span>美元</span><span>通胀</span><span>流动性</span></div></Panel>
    <Panel title="数据能力" eyebrow="CAPABILITY"><CapabilityDetails capabilities={item.capabilities} advanced={advanced} /></Panel>
    <DetailsDisclosure label="数据详情"><dl class="detail-grid"><div><dt>来源</dt><dd>{item.details.provider ?? "未记录"}</dd></div><div><dt>质量</dt><dd>{item.details.quality ?? "UNKNOWN"}</dd></div><div><dt>限制</dt><dd>{item.details.limitation ?? "无额外记录"}</dd></div><div><dt>最新时间</dt><dd>{item.details.timestamp ?? "—"}</dd></div>{item.derived ? <><div><dt>公式</dt><dd>{item.details.derivation?.formula ?? "—"}</dd></div><div><dt>计算版本</dt><dd>{item.details.derivation?.calculation_version ?? "—"}</dd></div></> : null}</dl></DetailsDisclosure>
  </>;
}

function CountryDrawerContent({ detail, advanced, onOpenMarket, onOpenEvent }: { detail: ProductCountryDetail; advanced: boolean; onOpenMarket: (item: ProductMarketItem) => void; onOpenEvent: (id: string) => void }) {
  const [historyHorizon, setHistoryHorizon] = useState<ChartHorizon>("3m");
  const dimension = detail.selected_dimension;
  const historyPoints = detail.state_history.map((item) => ({ time: item.date, value: item.value }));
  const directionLabels: Record<string, string> = { strong: "偏强", weak: "偏弱", mixed: "分化", unavailable: "缺失" };
  const series = detail.key_series.filter((item) => !dimension || item.dimension === dimension.key).slice(0, 10);
  return <>
    <div class="drawer-kpi"><strong>{dimension ? `${detail.country.label} · ${dimension.label}` : detail.country.label}</strong><Badge tone={detail.country.status === "available" ? "good" : "warn"}>{detail.country.available_dimensions.length} 个维度</Badge></div>
    {dimension ? <Panel title="当前状态" eyebrow="MACRO DIMENSION"><dl class="detail-grid"><div><dt>分数</dt><dd>{dimension.score == null ? "—" : dimension.score.toFixed(2)}</dd></div><div><dt>方向</dt><dd>{directionLabels[dimension.direction] ?? dimension.direction}</dd></div><div><dt>动量</dt><dd>{dimension.momentum == null ? "—" : dimension.momentum.toFixed(2)}</dd></div><div><dt>覆盖率</dt><dd>{Math.round(dimension.coverage * 100)}%</dd></div><div><dt>置信度</dt><dd>{Math.round(dimension.confidence * 100)}%</dd></div></dl></Panel> : null}
    <Panel title={dimension ? "主要驱动" : "关键序列"} eyebrow="OBSERVED INPUTS"><div class="research-list research-list--compact">{series.map((item) => <div class="research-row" key={item.key}><div><strong>{item.title}</strong><span>{item.dimension_label} · {item.period_start ?? "时间未记录"}</span></div><span>{item.latest_value == null ? "—" : item.latest_value.toLocaleString()}</span></div>)}{!series.length ? <p class="muted">暂无可用关键序列。</p> : null}</div></Panel>
    {dimension ? <Panel title="状态历史" eyebrow="REAL DAILY SNAPSHOTS" aside={<Badge tone="info">{detail.state_history.length} 个真实点</Badge>}>{historyPoints.length ? <><div class="chart-horizons">{([['1w', '7D'], ['1m', '30D'], ['3m', '90D'], ['1y', '1Y']] as Array<[ChartHorizon, string]>).map(([value, label]) => <button type="button" class={historyHorizon === value ? "active" : ""} onClick={() => setHistoryHorizon(value)} key={value}>{label}</button>)}</div><TimeSeriesChart points={historyPoints} horizon={historyHorizon} /></> : <p class="muted">尚未积累该国家维度的每日状态快照，不生成虚假历史。</p>}</Panel> : null}
    {dimension && detail.comparisons.length ? <Panel title="全球比较" eyebrow="SAME DIMENSION"><div class="research-list research-list--compact">{detail.comparisons.map((item) => <div class="research-row" key={item.country_key}><div><strong>{item.country_label}</strong><span>覆盖率 {Math.round(item.coverage * 100)}%</span></div><span>{item.score.toFixed(2)}</span></div>)}</div></Panel> : null}
    {detail.markets.length ? <Panel title="相关市场" eyebrow="DAILY CONTEXT"><div class="context-links">{detail.markets.map((item) => <button type="button" class="context-link" key={item.key} onClick={() => onOpenMarket(item)}>{item.label} <strong>{item.formatted_value}</strong></button>)}</div></Panel> : null}
    {(detail.recent_releases.length || detail.upcoming_releases.length) ? <Panel title="事件" eyebrow="RECENT / UPCOMING"><div class="research-list research-list--compact">{[...detail.recent_releases.slice(0, 3), ...detail.upcoming_releases.slice(0, 3)].map((item) => <button type="button" class="research-row" key={item.id} onClick={() => onOpenEvent(item.id)}><div><strong>{item.title}</strong><span>{item.period_label}</span></div><Badge tone={item.status === "released" ? "good" : "info"}>{item.status === "released" ? "已发布" : "待发布"}</Badge></button>)}</div></Panel> : null}
    <DetailsDisclosure label="数据边界"><p class="method-note">{detail.limitations.join(" ") || "基于当前本地 observed 数据按时点计算。"}</p>{advanced ? <p class="method-note">方法版本：{detail.methodology_version} · 历史范围：{detail.history_scope}</p> : null}</DetailsDisclosure>
  </>;
}

function SeriesDrawerContent({ data }: { data: Record<string, unknown> }) {
  const points = (data.points as Array<Record<string, unknown>> ?? []);
  const byPeriod = new Map<string, number>();
  for (const point of points) if (point.period && point.transformed != null) byPeriod.set(String(point.period), Number(point.transformed));
  const chart = [...byPeriod.entries()].map(([time, value]) => ({ time, value }));
  const latest = chart.at(-1);
  return <><div class="drawer-kpi"><strong>{String(data.title ?? data.canonical_key ?? "Series")}</strong><Badge tone="info">{String(data.frequency ?? "series")}</Badge></div><Panel title="历史轨迹" eyebrow="OBSERVED SERIES"><TimeSeriesChart points={chart} horizon="1y" /></Panel><Panel title="序列信息" eyebrow="SERIES DETAIL"><dl class="detail-grid"><div><dt>最新值</dt><dd>{latest ? latest.value.toLocaleString() : "—"}</dd></div><div><dt>单位</dt><dd>{String(data.unit ?? "—")}</dd></div><div><dt>转换</dt><dd>{String(data.transform ?? "raw")}</dd></div><div><dt>数据模式</dt><dd>{String(data.data_mode ?? "—")}</dd></div></dl></Panel><DetailsDisclosure label="数据限制"><p class="method-note">{((data.limitations as string[]) ?? []).join(" ") || "未记录额外限制。"}</p></DetailsDisclosure></>;
}

export function App() {
  const initial = useMemo(routeState, []);
  const [view, setView] = useState<ProductView>(initial.view);
  const [data, setData] = useState<ProductTodayResponse | null>(null);
  const [marketsData, setMarketsData] = useState<ProductMarketsResponse | null>(null);
  const [macroData, setMacroData] = useState<ProductMacroResponse | null>(null);
  const [eventsData, setEventsData] = useState<ProductEventsResponse | null>(null);
  const [releases, setReleases] = useState<ReleaseSummary[]>([]);
  const [selectedRelease, setSelectedRelease] = useState<ReleaseSummary | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ProductEventDetail | null>(null);
  const [selectedMarketKey, setSelectedMarketKey] = useState<string | null>(initial.params.get("asset"));
  const [selectedMarket, setSelectedMarket] = useState<ProductMarketItem | null>(null);
  const [selectedCountryKey, setSelectedCountryKey] = useState<string | null>(initial.params.get("country"));
  const [selectedDimension, setSelectedDimension] = useState<string | null>(initial.params.get("dimension"));
  const [countryDetail, setCountryDetail] = useState<ProductCountryDetail | null>(null);
  const [selectedSeriesKey, setSelectedSeriesKey] = useState<string | null>(initial.params.get("series"));
  const [seriesDetail, setSeriesDetail] = useState<Record<string, unknown> | null>(null);
  const [selectedThesis, setSelectedThesis] = useState<string | null>(initial.params.get("thesis"));
  const [requestedRelease, setRequestedRelease] = useState<string | null>(initial.params.get("release"));
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [learningMode, setLearningMode] = useState(() => window.localStorage.getItem("worldstate.learning_mode") === "on");
  const [advancedMode, setAdvancedMode] = useState(() => window.localStorage.getItem("worldstate.advanced_mode") === "on");
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem("worldstate.sidebar_collapsed") === "on");
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [searchEntities, setSearchEntities] = useState<SearchResult[]>([]);

  const refresh = async () => {
    setLoading(true); setError(null);
    const projection = view === "today" ? api.productToday() : view === "markets" ? api.productMarkets() : view === "macro" ? api.productMacro() : view === "events" ? api.productEvents() : Promise.resolve(null);
    const [projectionResult, healthResult] = await Promise.allSettled([projection, api.health()]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (projectionResult.status === "rejected") setError("WorldState 数据暂时无法加载，请重试。");
    else if (projectionResult.value) {
      if (view === "today") setData(projectionResult.value as ProductTodayResponse);
      if (view === "markets") setMarketsData(projectionResult.value as ProductMarketsResponse);
      if (view === "macro") setMacroData(projectionResult.value as ProductMacroResponse);
      if (view === "events") {
        const events = projectionResult.value as ProductEventsResponse;
        setEventsData(events); setReleases(events.items);
        setSelectedRelease(events.items.find((item) => item.id === requestedRelease) ?? events.items.find((item) => item.id === events.default_event_id) ?? preferredRelease(events.items));
      }
    }
    setLoading(false);
  };

  useEffect(() => { void refresh(); }, [view]);
  useEffect(() => {
    const params = new URLSearchParams();
    if (view === "markets" && selectedMarketKey) params.set("asset", selectedMarketKey);
    if (view === "macro" && selectedCountryKey) params.set("country", selectedCountryKey);
    if (view === "macro" && selectedDimension) params.set("dimension", selectedDimension);
    if (view === "macro" && selectedSeriesKey) params.set("series", selectedSeriesKey);
    if (view === "events" && selectedRelease) params.set("release", selectedRelease.id);
    if (view === "research" && selectedThesis) params.set("thesis", selectedThesis);
    window.history.replaceState(null, "", `#${view}${params.size ? `?${params.toString()}` : ""}`);
  }, [view, selectedMarketKey, selectedCountryKey, selectedDimension, selectedSeriesKey, selectedRelease?.id, selectedThesis]);
  useEffect(() => {
    if (view !== "markets" || !selectedMarketKey) return;
    const item = marketsData?.items.find((row) => row.key === selectedMarketKey) ?? data?.markets.find((row) => row.key === selectedMarketKey);
    if (item) setSelectedMarket(item);
  }, [view, selectedMarketKey, marketsData, data]);
  useEffect(() => {
    if (view !== "macro" || !selectedCountryKey) return;
    let active = true;
    setCountryDetail(null);
    void api.productCountry(selectedCountryKey, selectedDimension ?? undefined).then((detail) => { if (active) setCountryDetail(detail); }).catch(() => { if (active) setCountryDetail(null); });
    return () => { active = false; };
  }, [view, selectedCountryKey, selectedDimension]);
  useEffect(() => {
    if (view !== "macro" || !selectedSeriesKey) return;
    let active = true;
    setSeriesDetail(null);
    void api.seriesHistory(selectedSeriesKey).then((detail) => { if (active) setSeriesDetail(detail); }).catch(() => { if (active) setSeriesDetail(null); });
    return () => { active = false; };
  }, [view, selectedSeriesKey]);
  useEffect(() => {
    if (view !== "events" || !selectedRelease || selectedDetail?.id === selectedRelease.id) return;
    void api.productEvent(selectedRelease.id).then(setSelectedDetail).catch(() => setSelectedDetail(null));
  }, [view, selectedRelease?.id]);
  useEffect(() => { const listener = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandOpen(true); } }; window.addEventListener("keydown", listener); return () => window.removeEventListener("keydown", listener); }, []);

  const openMarket = (item: ProductMarketItem) => { setView("markets"); setSelectedMarketKey(item.key); setSelectedMarket(item); setSelectedCountryKey(null); setSelectedSeriesKey(null); };
  const openCountry = (item: ProductCountry, dimension?: string) => { setView("macro"); setSelectedCountryKey(item.key); setSelectedDimension(dimension ?? null); setSelectedSeriesKey(null); setSelectedMarket(null); };
  const openDimension = (item: ProductDimension) => { const country = data?.global.find((row) => row.key === "USA") ?? data?.global[0]; if (country) openCountry(country, item.key); };
  const openSeries = (key: string) => { setView("macro"); setSelectedSeriesKey(key); setSelectedCountryKey(null); setSelectedDimension(null); setSelectedMarket(null); };
  const openEvent = async (id: string) => { setRequestedRelease(id); setView("events"); const item = releases.find((row) => row.id === id) ?? eventsData?.items.find((row) => row.id === id); if (item) setSelectedRelease(item); try { setSelectedDetail(await api.productEvent(id)); } catch { setSelectedDetail(null); } };
  const openThesis = (id: string) => { setSelectedThesis(id); setView("research"); };
  const closeDrawer = () => { setSelectedMarketKey(null); setSelectedMarket(null); setSelectedCountryKey(null); setSelectedDimension(null); setCountryDetail(null); setSelectedSeriesKey(null); setSeriesDetail(null); };

  useEffect(() => {
    const query = commandQuery.trim();
    if (query.length < 2) { setSearchEntities([]); return; }
    let active = true;
    const seriesQuery = query.split(/\s+/).at(-1) ?? query;
    const timer = window.setTimeout(() => void Promise.allSettled([api.series(seriesQuery), api.theses(), api.productMarkets(), api.productEvents("observed", 150)]).then(([seriesResult, thesesResult, marketResult, eventResult]) => {
      if (!active) return;
      const next: SearchResult[] = [];
      if (marketResult.status === "fulfilled") for (const item of marketResult.value.items.filter((row) => `${row.label} ${row.key} ${row.symbol ?? ""}`.toLowerCase().includes(query.toLowerCase())).slice(0, 4)) next.push({ key: `market:${item.key}`, label: item.label, note: "打开市场详情", action: () => openMarket(item) });
      if (seriesResult.status === "fulfilled") for (const item of seriesResult.value.slice(0, 5)) { const key = String(item.canonical_key ?? item.key ?? item.id ?? "series"); next.push({ key: `series:${key}`, label: String(item.title ?? item.name ?? key), note: "打开宏观序列", action: () => openSeries(key) }); }
      if (eventResult.status === "fulfilled") for (const item of eventResult.value.items.filter((row) => `${row.title} ${row.release_type} ${row.period_label}`.toLowerCase().includes(query.toLowerCase())).slice(0, 4)) next.push({ key: `event:${item.id}`, label: item.title, note: `${item.release_type} · ${item.period_label}`, action: () => void openEvent(item.id) });
      if (thesesResult.status === "fulfilled") for (const item of thesesResult.value.filter((row) => `${row.title ?? ""} ${row.thesis ?? ""}`.toLowerCase().includes(query.toLowerCase())).slice(0, 3)) { const id = String(item.id); next.push({ key: `thesis:${id}`, label: String(item.title ?? "Thesis"), note: "打开研究判断", action: () => openThesis(id) }); }
      setSearchEntities(next);
    }), 220);
    return () => { active = false; window.clearTimeout(timer); };
  }, [commandQuery]);

  const toggleLearning = () => setLearningMode((value) => { const next = !value; window.localStorage.setItem("worldstate.learning_mode", next ? "on" : "off"); return next; });
  const toggleAdvanced = () => setAdvancedMode((value) => { const next = !value; window.localStorage.setItem("worldstate.advanced_mode", next ? "on" : "off"); return next; });
  const toggleCollapsed = () => setCollapsed((value) => { const next = !value; window.localStorage.setItem("worldstate.sidebar_collapsed", next ? "on" : "off"); return next; });
  const results = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    const nav = NAV.filter((item) => !query || `${item.label} ${item.note}`.toLowerCase().includes(query)).map((item) => ({ key: `nav:${item.key}`, label: item.label, note: item.note, action: () => setView(item.key) }));
    const countryAliases: Record<string, string> = { USA: "united states america us 美国", CHN: "china cn 中国", EA19: "euro area europe ea 欧元区", JPN: "japan jp 日本", GBR: "united kingdom uk britain 英国" };
    const countries = (macroData?.countries ?? data?.global ?? []).filter((item) => !query || `${item.label} ${item.key} ${countryAliases[item.key] ?? ""}`.toLowerCase().includes(query)).map((item) => ({ key: `country:${item.key}`, label: item.label, note: "打开国家详情", action: () => openCountry(item) }));
    return [...nav, ...countries, ...searchEntities].slice(0, 16);
  }, [commandQuery, macroData, data, searchEntities]);

  const pageTitle = NAV.find((item) => item.key === view)?.label ?? (view === "data-control" ? "Data Sources" : "Data & Methods");
  const drawer = selectedMarket ? { title: selectedMarket.label, body: <MarketDrawerContent item={selectedMarket} advanced={advancedMode} /> } : countryDetail ? { title: countryDetail.selected_dimension ? `${countryDetail.country.label} · ${countryDetail.selected_dimension.label}` : countryDetail.country.label, body: <CountryDrawerContent detail={countryDetail} advanced={advancedMode} onOpenMarket={openMarket} onOpenEvent={(id) => void openEvent(id)} /> } : seriesDetail ? { title: String(seriesDetail.title ?? selectedSeriesKey ?? "Series"), body: <SeriesDrawerContent data={seriesDetail} /> } : null;

  return <div class={collapsed ? "terminal-shell terminal-shell--collapsed" : "terminal-shell"}>
    <aside class="sidebar"><div class="brand"><div class="brand__mark">W<span>S</span></div><div><strong>WorldState</strong><span>Macro Research Terminal</span></div></div><button type="button" class="shell-toggle" onClick={toggleCollapsed} aria-label="收起侧栏">{collapsed ? ">" : "<"}</button><nav aria-label="主导航">{NAV.map((item, index) => <button type="button" key={item.key} class={view === item.key ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView(item.key)}><span class="nav-item__index">{String(index + 1).padStart(2, "0")}</span><span><strong>{item.label}</strong><small>{item.note}</small></span></button>)}</nav><div class="sidebar__advanced"><button type="button" class={view === "data-control" ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView("data-control")}><span class="nav-item__index">A1</span><span><strong>Data Sources</strong><small>同步与导入</small></span></button><button type="button" class={view === "data-methods" ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView("data-methods")}><span class="nav-item__index">A2</span><span><strong>Methods</strong><small>高级详情</small></span></button></div></aside>
    <main class="main"><header class="topbar"><div><span class="topbar__kicker">WORLDSTATE / MACRO TERMINAL</span><strong>{pageTitle}</strong></div><div class="topbar__status"><button type="button" class="shell-command" onClick={() => setCommandOpen(true)}><span>搜索市场、国家、事件与研究</span><kbd>Ctrl K</kbd></button><button type="button" class={learningMode ? "mode-toggle mode-toggle--active" : "mode-toggle"} onClick={toggleLearning}>{learningMode ? "学习模式：开" : "学习模式"}</button><button type="button" class={advancedMode ? "mode-toggle mode-toggle--active" : "mode-toggle"} onClick={toggleAdvanced}>{advancedMode ? "高级" : "标准"}</button><Badge tone={health?.database.status === "ok" ? "good" : "warn"}>{health?.database.status === "ok" ? "就绪" : "连接中"}</Badge></div></header>
      {loading ? <StateMessage title="正在准备 WorldState" detail="加载宏观状态、市场和数据能力。" /> : error ? <StateMessage title="WorldState 无法加载" detail={error} action={<button type="button" class="button-primary" onClick={() => void refresh()}>重试</button>} /> : <WorkspaceBoundary key={view}>{view === "today" && data ? <TodayBoard data={data} learningMode={learningMode} onOpenDimension={openDimension} onOpenMarket={openMarket} onOpenCountry={(item) => openCountry(item)} onOpenEvent={(id) => void openEvent(id)} /> : null}{view === "markets" && marketsData ? <MarketsBoard items={marketsData.items} onOpen={openMarket} /> : null}{view === "macro" && macroData ? <MacroBoard data={macroData} selectedCountryKey={selectedCountryKey} onOpenCountry={openCountry} /> : null}{view === "events" ? <EventsBoard releases={releases} selected={selectedRelease} detail={selectedDetail} onSelect={(item) => void openEvent(item.id)} onOpenLab={() => setView("events")} onOpenDataSources={() => setView("data-control")} /> : null}{view === "research" ? <ResearchWorkspace selectedId={selectedThesis} onSelect={setSelectedThesis} /> : null}{view === "data-control" ? <DataControlWorkspace /> : null}{view === "data-methods" ? <DataMethodsWorkspace /> : null}</WorkspaceBoundary>}
    </main>
    {drawer ? <Drawer title={drawer.title} onClose={closeDrawer}>{drawer.body}</Drawer> : null}
    {commandOpen ? <div class="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setCommandOpen(false); }}><section class="modal command-palette" role="dialog" aria-modal="true"><div class="modal__header"><h2>搜索 WorldState</h2><button type="button" class="modal__close" onClick={() => setCommandOpen(false)}>×</button></div><div class="modal__body"><input autoFocus value={commandQuery} onInput={(event) => setCommandQuery(event.currentTarget.value)} placeholder="试试：黄金、中国 CPI、FOMC" /><div class="command-results">{results.map((result) => <button type="button" key={result.key} onClick={() => { result.action(); setCommandOpen(false); setCommandQuery(""); }}><strong>{result.label}</strong><span>{result.note}</span></button>)}{!results.length ? <p class="muted">没有匹配结果</p> : null}</div></div></section></div> : null}
  </div>;
}
