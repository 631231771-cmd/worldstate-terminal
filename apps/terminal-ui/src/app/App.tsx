import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../api/client";
import { Badge, DetailsDisclosure, Drawer, Panel, StateMessage } from "../components/Primitives";
import { TimeSeriesChart, type ChartHorizon } from "../components/TimeSeriesChart";
import { WorkspaceBoundary } from "../components/WorkspaceBoundary";
import type { ReleaseSummary } from "../types";
import type { ProductCountry, ProductDimension, ProductEventDetail, ProductEventsResponse, ProductMarketItem, ProductMarketsResponse, ProductMacroResponse, ProductTodayResponse } from "../types/product";
import { DataControlWorkspace } from "../workspaces/data-control/DataControlWorkspace";
import { DataMethodsWorkspace } from "../workspaces/data-methods/DataMethodsWorkspace";
import { ResearchWorkspace } from "../workspaces/research/ResearchWorkspace";
import { EventsBoard } from "../workspaces/rebuild/EventsBoard";
import { MacroBoard } from "../workspaces/rebuild/MacroBoard";
import { MarketsBoard } from "../workspaces/rebuild/MarketsBoard";
import { TodayBoard } from "../workspaces/rebuild/TodayBoard";
import { EventLabWorkspace } from "../workspaces/event-lab/EventLabWorkspace";

type ProductView = "today" | "markets" | "macro" | "events" | "event-lab" | "research" | "data-control" | "data-methods";
type DrawerState = { title: string; body: ComponentChildren } | null;
const NAV = [
  { key: "today" as const, label: "Today", note: "Current environment" },
  { key: "markets" as const, label: "Markets", note: "Cross-asset board" },
  { key: "macro" as const, label: "Macro", note: "Global macro matrix" },
  { key: "events" as const, label: "Events", note: "Calendar and releases" },
  { key: "research" as const, label: "Research", note: "Theses and replay" },
];

function initialView(): ProductView {
  const hash = window.location.hash.replace("#", "").split("?")[0] ?? "";
  if (hash === "markets" || hash === "cross-asset") return "markets";
  if (hash === "macro") return "macro";
  if (["world-state", "countries", "series"].includes(hash)) return "macro";
  if (hash === "event-lab") return "events";
  if (["events", "releases", "calendar"].includes(hash)) return "events";
  if (hash === "research") return "research";
  if (hash === "data-control") return "data-control";
  if (hash === "data-methods") return "data-methods";
  return "today";
}

function preferredRelease(items: ReleaseSummary[]): ReleaseSummary | null {
  const rank = (item: ReleaseSummary) => item.analysis_status === "completed" && item.reproducibility_status === "complete" ? 0 : item.status === "released" ? 1 : 2;
  return [...items].sort((a, b) => rank(a) - rank(b) || String(b.released_at ?? b.scheduled_at).localeCompare(String(a.released_at ?? a.scheduled_at)))[0] ?? null;
}

function CapabilityDetails({ capabilities, advanced }: { capabilities: Record<string, { available: boolean; status: string; reason: string | null }>; advanced: boolean }) {
  const names = ["CURRENT_STATE", "MACRO_HISTORY", "POINT_IN_TIME", "EVENT_INTRADAY", "HISTORICAL_REPLAY", "SURPRISE_ELIGIBLE"];
  const labels: Record<string, string> = { CURRENT_STATE: "当前状态", MACRO_HISTORY: "宏观历史", POINT_IN_TIME: "PIT", EVENT_INTRADAY: "事件分钟", HISTORICAL_REPLAY: "历史回放", SURPRISE_ELIGIBLE: "惊喜计算" };
  return <dl class="detail-grid">{names.map((name) => <div key={name}><dt>{labels[name] ?? name}</dt><dd>{capabilities[name]?.available ? "可用" : advanced ? capabilities[name]?.reason ?? "不可用" : "不可用"}</dd></div>)}</dl>;
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
    <DetailsDisclosure label="数据详情"><dl class="detail-grid"><div><dt>来源</dt><dd>{item.details.provider ?? "未记录"}</dd></div><div><dt>质量</dt><dd>{item.details.quality ?? "UNKNOWN"}</dd></div><div><dt>限制</dt><dd>{item.details.limitation ?? "无额外记录"}</dd></div><div><dt>最新时间</dt><dd>{item.details.timestamp ?? "—"}</dd></div>{item.derived ? <><div><dt>公式</dt><dd>{item.details.derivation?.formula ?? "—"}</dd></div><div><dt>计算版本</dt><dd>{item.details.derivation?.calculation_version ?? "—"}</dd></div></> : null}<div><dt>连续区段</dt><dd>{item.details.continuity_segments?.length ?? 0}</dd></div></dl></DetailsDisclosure>
  </>;
}

export function App() {
  const [view, setView] = useState<ProductView>(initialView);
  const [data, setData] = useState<ProductTodayResponse | null>(null);
  const [marketsData, setMarketsData] = useState<ProductMarketsResponse | null>(null);
  const [macroData, setMacroData] = useState<ProductMacroResponse | null>(null);
  const [eventsData, setEventsData] = useState<ProductEventsResponse | null>(null);
  const [releases, setReleases] = useState<ReleaseSummary[]>([]);
  const [selectedRelease, setSelectedRelease] = useState<ReleaseSummary | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ProductEventDetail | null>(null);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [learningMode, setLearningMode] = useState(() => window.localStorage.getItem("worldstate.learning_mode") === "on");
  const [advancedMode, setAdvancedMode] = useState(() => window.localStorage.getItem("worldstate.advanced_mode") === "on");
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem("worldstate.sidebar_collapsed") === "on");
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [searchEntities, setSearchEntities] = useState<Array<{ key: string; label: string; note: string; action: () => void }>>([]);

  const refresh = async () => {
    setLoading(true); setError(null);
    const todayRequest = view === "today" ? api.productToday() : Promise.resolve(null as ProductTodayResponse | null);
    const marketsRequest = view === "markets" ? api.productMarkets() : Promise.resolve(null as ProductMarketsResponse | null);
    const macroRequest = view === "macro" ? api.productMacro() : Promise.resolve(null as ProductMacroResponse | null);
    const eventsRequest = view === "today" || view === "events" || view === "event-lab" ? api.productEvents() : Promise.resolve(null as ProductEventsResponse | null);
    const [productResult, marketsResult, macroResult, eventsResult, healthResult] = await Promise.allSettled([todayRequest, marketsRequest, macroRequest, eventsRequest, api.health()]);
    if (productResult.status === "fulfilled" && productResult.value) setData(productResult.value);
    if (marketsResult.status === "fulfilled" && marketsResult.value) setMarketsData(marketsResult.value);
    if (macroResult.status === "fulfilled" && macroResult.value) {
      const macro = macroResult.value;
      setMacroData(macro);
      setData((current) => current ?? {
        as_of: macro.as_of,
        data_mode: macro.data_mode,
        methodology_version: macro.methodology_version,
        macro_snapshot: [], markets: [], what_changed: [], upcoming: [], latest_research: [],
        global: macro.countries, watch_next: [], capability_summary: {}, limitations: macro.limitations,
      });
    }
    if (eventsResult.status === "fulfilled" && eventsResult.value) {
      const events = eventsResult.value;
      setEventsData(events); setReleases(events.items); setSelectedRelease((current) => current ?? events.items.find((item) => item.id === events.default_event_id) ?? preferredRelease(events.items));
    }
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    const projectionResults = [productResult, marketsResult, macroResult, eventsResult].filter((result) => result.status !== "fulfilled" || result.value !== null);
    if (projectionResults.length && projectionResults.every((result) => result.status === "rejected")) setError("WorldState 数据暂时无法加载，请重试。");
    setLoading(false);
  };

  useEffect(() => { void refresh(); }, [view]);
  useEffect(() => { window.history.replaceState(null, "", `#${view}${selectedRelease ? `?release=${encodeURIComponent(selectedRelease.id)}` : ""}`); }, [view, selectedRelease]);
  useEffect(() => {
    if (view !== "events" || !selectedRelease || selectedDetail?.id === selectedRelease.id) return;
    void api.productEvent(selectedRelease.id).then(setSelectedDetail).catch(() => setSelectedDetail(null));
  }, [view, selectedRelease?.id]);
  useEffect(() => { const listener = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandOpen(true); } }; window.addEventListener("keydown", listener); return () => window.removeEventListener("keydown", listener); }, []);
  useEffect(() => {
    const listener = (event: Event) => {
      const destination = (event as CustomEvent<ProductView>).detail;
      if (destination) setView(destination);
    };
    window.addEventListener("worldstate:navigate", listener);
    return () => window.removeEventListener("worldstate:navigate", listener);
  }, []);
  useEffect(() => {
    const query = commandQuery.trim();
    if (query.length < 2) { setSearchEntities([]); return; }
    let active = true;
    void Promise.allSettled([api.series(query), api.theses()]).then(([seriesResult, thesesResult]) => {
      if (!active) return;
      const next: Array<{ key: string; label: string; note: string; action: () => void }> = [];
      if (seriesResult.status === "fulfilled") {
        for (const item of seriesResult.value.slice(0, 5)) {
          const key = String(item.canonical_key ?? item.key ?? item.id ?? "series");
          next.push({ key: `series:${key}`, label: String(item.title ?? item.name ?? key), note: "Open series", action: () => setView("macro") });
        }
      }
      if (thesesResult.status === "fulfilled") {
        for (const item of thesesResult.value.slice(0, 3)) {
          const key = String(item.id ?? item.key ?? "thesis");
          next.push({ key: `thesis:${key}`, label: String(item.title ?? item.name ?? "Thesis"), note: "Open research", action: () => setView("research") });
        }
      }
      setSearchEntities(next);
    });
    return () => { active = false; };
  }, [commandQuery]);

  const openEvent = async (id: string) => {
    const item = releases.find((release) => release.id === id) ?? data?.latest_research.find((release) => release.id === id) ?? null;
    if (item) setSelectedRelease(item);
    setView("events");
    try { setSelectedDetail(await api.productEvent(id)); } catch { setSelectedDetail(null); }
  };
  const openMarket = (item: ProductMarketItem) => {
    setDrawer({ title: item.label, body: <MarketDrawerContent item={item} advanced={advancedMode} /> });
  };
  const openDimension = (item: ProductDimension) => setDrawer({ title: item.label, body: <><div class="drawer-kpi"><strong>{item.score == null ? "—" : item.score.toFixed(2)}</strong><Badge tone="info">{item.direction}</Badge></div><Panel title="Current state" eyebrow="MACRO DIMENSION"><dl class="detail-grid"><div><dt>Momentum</dt><dd>{item.momentum == null ? "—" : item.momentum.toFixed(2)}</dd></div><div><dt>Confidence</dt><dd>{Math.round(item.confidence * 100)}%</dd></div><div><dt>Coverage</dt><dd>{Math.round(item.coverage * 100)}%</dd></div></dl></Panel><Panel title="Top drivers" eyebrow="STRUCTURED INPUTS"><ul class="boundary-list">{item.drivers.map((driver) => <li key={driver.series_key}>{driver.title ?? driver.series_key ?? "Series"}</li>)}</ul></Panel><DetailsDisclosure label="Why this state?"><p class="method-note">This is a structured state signal, not a trading signal or a single causal conclusion.</p></DetailsDisclosure></> });
  const openCountry = (item: ProductCountry) => setDrawer({ title: item.label, body: <><div class="drawer-kpi"><strong>{item.status}</strong><Badge tone={item.status === "available" ? "good" : item.status === "partial" ? "warn" : "neutral"}>{item.available_dimensions.length} dimensions</Badge></div><Panel title="Country state" eyebrow="COUNTRY DETAIL"><div class="board-grid board-grid--markets">{Object.entries(item.dimensions).map(([key, value]) => <div class="metric-tile" key={key}><span class="metric-tile__label">{key}</span><strong class="metric-tile__value">{value.score == null ? "—" : value.score.toFixed(2)}</strong><span class="metric-tile__meta">{value.direction}</span></div>)}</div></Panel><DetailsDisclosure label="Data boundaries"><p class="method-note">{item.details.limitations.join(" ") || "Computed from local Series and Observation data."}</p></DetailsDisclosure></> });
  const toggleLearning = () => setLearningMode((value) => { const next = !value; window.localStorage.setItem("worldstate.learning_mode", next ? "on" : "off"); return next; });
  const toggleAdvanced = () => setAdvancedMode((value) => { const next = !value; window.localStorage.setItem("worldstate.advanced_mode", next ? "on" : "off"); return next; });
  const toggleCollapsed = () => setCollapsed((value) => { const next = !value; window.localStorage.setItem("worldstate.sidebar_collapsed", next ? "on" : "off"); return next; });
  const results = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    const nav = NAV.filter((item) => !query || `${item.label} ${item.note}`.toLowerCase().includes(query)).map((item) => ({ key: item.key, label: item.label, note: item.note, action: () => setView(item.key) }));
    const markets = (marketsData?.items ?? data?.markets ?? []).filter((item) => !query || `${item.label} ${item.key} ${item.symbol ?? ""}`.toLowerCase().includes(query)).map((item) => ({ key: item.key, label: item.label, note: "Open market detail", action: () => openMarket(item) }));
    const events = releases.filter((item) => !query || `${item.title} ${item.release_type} ${item.period_label}`.toLowerCase().includes(query)).slice(0, 8).map((item) => ({ key: item.id, label: item.title, note: item.period_label, action: () => void openEvent(item.id) }));
    const countries = (data?.global ?? []).filter((item) => !query || `${item.label} ${item.key}`.toLowerCase().includes(query)).map((item) => ({ key: `country:${item.key}`, label: item.label, note: "Open country detail", action: () => openCountry(item) }));
    return [...nav, ...markets, ...countries, ...events, ...searchEntities].slice(0, 16);
  }, [commandQuery, data, marketsData, releases, searchEntities]);
  const pageTitle = NAV.find((item) => item.key === view)?.label ?? (view === "event-lab" ? "Event Lab" : view === "data-control" ? "Data Sources" : "Data & Methods");
  return <div class={collapsed ? "terminal-shell terminal-shell--collapsed" : "terminal-shell"}><aside class="sidebar"><div class="brand"><div class="brand__mark">W<span>S</span></div><div><strong>WorldState</strong><span>Macro Research Terminal</span></div></div><button type="button" class="shell-toggle" onClick={toggleCollapsed} aria-label="Toggle sidebar">{collapsed ? ">" : "<"}</button><nav aria-label="Primary navigation">{NAV.map((item, index) => <button type="button" key={item.key} class={view === item.key ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView(item.key)}><span class="nav-item__index">{String(index + 1).padStart(2, "0")}</span><span><strong>{item.label}</strong><small>{item.note}</small></span></button>)}</nav><div class="sidebar__advanced"><button type="button" class={view === "data-control" ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView("data-control")}><span class="nav-item__index">A1</span><span><strong>Data Sources</strong><small>Settings and import</small></span></button><button type="button" class={view === "data-methods" ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView("data-methods")}><span class="nav-item__index">A2</span><span><strong>Methods</strong><small>Advanced details</small></span></button></div></aside><main class="main"><header class="topbar"><div><span class="topbar__kicker">WORLDSTATE / MACRO TERMINAL</span><strong>{pageTitle}</strong></div><div class="topbar__status"><button type="button" class="shell-command" onClick={() => setCommandOpen(true)}><span>Search markets, countries, events</span><kbd>Ctrl K</kbd></button><button type="button" class={learningMode ? "mode-toggle mode-toggle--active" : "mode-toggle"} onClick={toggleLearning}>{learningMode ? "Learning on" : "Learning"}</button><button type="button" class={advancedMode ? "mode-toggle mode-toggle--active" : "mode-toggle"} onClick={toggleAdvanced}>{advancedMode ? "Advanced" : "Standard"}</button><Badge tone={health?.database.status === "ok" ? "good" : "warn"}>{health?.database.status === "ok" ? "Ready" : "Connecting"}</Badge></div></header>{loading ? <StateMessage title="Preparing WorldState" detail="Loading macro state, markets, and data capabilities." /> : error ? <StateMessage title="WorldState could not load" detail={error} action={<button type="button" class="button-primary" onClick={() => void refresh()}>Retry</button>} /> : <WorkspaceBoundary key={view}>{view === "today" && data ? <TodayBoard data={data} learningMode={learningMode} onOpenDimension={openDimension} onOpenMarket={openMarket} onOpenCountry={openCountry} onOpenEvent={(id) => void openEvent(id)} /> : null}{view === "markets" && (marketsData ?? data) ? <MarketsBoard items={(marketsData ?? { items: data?.markets ?? [] }).items} onOpen={openMarket} /> : null}{view === "macro" && data ? <MacroBoard countries={data.global} onOpenCountry={openCountry} /> : null}{view === "events" ? <EventsBoard releases={releases} selected={selectedRelease} detail={selectedDetail} onSelect={(item) => void openEvent(item.id)} onOpenLab={() => setView("events")} onOpenDataSources={() => setView("data-control")} /> : null}{view === "research" ? <ResearchWorkspace /> : null}{view === "data-control" ? <DataControlWorkspace /> : null}{view === "data-methods" ? <DataMethodsWorkspace /> : null}</WorkspaceBoundary>}</main>{drawer ? <Drawer title={drawer.title} onClose={() => setDrawer(null)}>{drawer.body}</Drawer> : null}{commandOpen ? <div class="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setCommandOpen(false); }}><section class="modal command-palette" role="dialog" aria-modal="true"><div class="modal__header"><h2>Search WorldState</h2><button type="button" class="modal__close" onClick={() => setCommandOpen(false)}>×</button></div><div class="modal__body"><input autoFocus value={commandQuery} onInput={(event) => setCommandQuery(event.currentTarget.value)} placeholder="Try gold, CPI, China" /> <div class="command-results">{results.map((result) => <button type="button" key={result.key} onClick={() => { result.action(); setCommandOpen(false); setCommandQuery(""); }}><strong>{result.label}</strong><span>{result.note}</span></button>)}{!results.length ? <p class="muted">No matches</p> : null}</div></div></section></div> : null}</div>;
}
