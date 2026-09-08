import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api } from "../api/client";
import { Badge, DetailsDisclosure, Drawer, Panel, StateMessage } from "../components/Primitives";
import { ConceptStrip } from "../components/ConceptHelp";
import { TimeSeriesChart, type ChartHorizon } from "../components/TimeSeriesChart";
import { WorkspaceBoundary } from "../components/WorkspaceBoundary";
import type { ReleaseSummary } from "../types";
import type { ProductCountry, ProductCountryDetail, ProductDimension, ProductEventDetail, ProductEventsResponse, ProductMarketItem, ProductMarketsResponse, ProductMacroResponse, ProductTodayResponse } from "../types/product";
import { DataControlWorkspace } from "../workspaces/data-control/DataControlWorkspace";
import { DataMethodsWorkspace } from "../workspaces/data-methods/DataMethodsWorkspace";
import { EventsBoard } from "../workspaces/rebuild/EventsBoard";
import { MacroBoard } from "../workspaces/rebuild/MacroBoard";
import { MarketsBoard } from "../workspaces/rebuild/MarketsBoard";


function CountryDrawerContent({ detail, advanced, learningMode, onOpenMarket, onOpenEvent }: { detail: ProductCountryDetail; advanced: boolean; learningMode: boolean; onOpenMarket: (item: ProductMarketItem) => void; onOpenEvent: (id: string) => void }) {
  const [historyHorizon, setHistoryHorizon] = useState<ChartHorizon>("3m");
  const dimension = detail.selected_dimension;
  const historyPoints = detail.state_history.map((item) => ({ time: item.date, value: item.value }));
  const directionLabels: Record<string, string> = { strong: "偏强", weak: "偏弱", mixed: "分化", unavailable: "缺失" };
  const series = detail.key_series.filter((item) => !dimension || item.dimension === dimension.key).slice(0, 10);
  return <>
    <div class="drawer-kpi"><strong>{dimension ? `${detail.country.label} · ${dimension.label}` : detail.country.label}</strong><Badge tone={detail.country.status === "available" ? "good" : "warn"}>{detail.country.available_dimensions.length} 个维度</Badge></div>
    {dimension ? <Panel title="当前状态" eyebrow="MACRO DIMENSION"><ConceptStrip concepts={dimension.key === "inflation" ? ["inflation"] : dimension.key === "growth" ? ["growth"] : dimension.key === "liquidity" ? ["liquidity"] : dimension.key === "policy_tightness" ? ["policy_tightness"] : []} active={learningMode} /><dl class="detail-grid"><div><dt>分数</dt><dd>{dimension.score == null ? "—" : dimension.score.toFixed(2)}</dd></div><div><dt>方向</dt><dd>{directionLabels[dimension.direction] ?? dimension.direction}</dd></div><div><dt>动量</dt><dd>{dimension.momentum == null ? "—" : dimension.momentum.toFixed(2)}</dd></div><div><dt>覆盖率</dt><dd>{Math.round(dimension.coverage * 100)}%</dd></div><div><dt>置信度</dt><dd>{Math.round(dimension.confidence * 100)}%</dd></div></dl></Panel> : null}
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


import { useReadModel } from "./useReadModel";
import { NAV, parseRoute, preferredRelease, type ProductView } from "./navigation";
import { RadarWorkspace } from "../workspaces/intelligence/RadarWorkspace";
import { MarketInvestigation } from "../workspaces/intelligence/MarketInvestigation";
import { MemoryWorkspace } from "../workspaces/intelligence/MemoryWorkspace";

type SearchResult = {key:string;label:string;note:string;action:()=>void};
function ReadStatus({label,resource,advanced}:{label:string;resource:{data:unknown;savedAt:string|null;refreshing:boolean;error:{message:string;technical:string}|null;refresh:()=>void};advanced:boolean}) {
  if (!resource.error && resource.data && !resource.refreshing) return null;
  return <div class={resource.error?"read-status read-status--error":"read-status"} role="status">
    <span>{resource.error ? `${label}刷新失败${resource.data?"，保留上次读取结果":""}。` : `${label}正在后台读取…`}{resource.savedAt ? ` 上次成功读取：${new Date(resource.savedAt).toLocaleString()}` : ""}</span>
    {resource.error?<><button type="button" onClick={resource.refresh}>重试</button>{advanced?<details><summary>技术原因</summary>{resource.error.technical}</details>:null}</>:null}
  </div>;
}

export function App() {
  const initial = useMemo(()=>parseRoute(window.location.hash),[]);
  const [view,setView] = useState<ProductView>(initial.view);
  const [requestedRelease,setRequestedRelease] = useState<string|null>(initial.params.get("release"));
  const [selectedMarketKey,setSelectedMarketKey] = useState<string|null>(initial.params.get("asset"));
  const [selectedCountryKey,setSelectedCountryKey] = useState<string|null>(initial.params.get("country"));
  const [selectedDimension,setSelectedDimension] = useState<string|null>(initial.params.get("dimension"));
  const [selectedSeriesKey,setSelectedSeriesKey] = useState<string|null>(initial.params.get("series"));
  const [seriesDetail,setSeriesDetail] = useState<Record<string,unknown>|null>(null);
  const [seriesError,setSeriesError] = useState<string|null>(null);
  const [selectedThesis,setSelectedThesis] = useState<string|null>(initial.params.get("thesis"));
  const [health,setHealth] = useState<Awaited<ReturnType<typeof api.health>>|null>(null);
  const [serviceError,setServiceError] = useState<string|null>(null);
  const [learningMode,setLearningMode] = useState(()=>localStorage.getItem("worldstate.learning_mode")==="on");
  const [advancedMode,setAdvancedMode] = useState(()=>localStorage.getItem("worldstate.advanced_mode")==="on");
  const [collapsed,setCollapsed] = useState(()=>localStorage.getItem("worldstate.sidebar_collapsed")==="on");
  const [toolsOpen,setToolsOpen] = useState(false);
  const [commandOpen,setCommandOpen] = useState(false);
  const [commandQuery,setCommandQuery] = useState("");
  const [searchEntities,setSearchEntities] = useState<SearchResult[]>([]);
  const mainRef=useRef<HTMLElement|null>(null);

  const markets=useReadModel("markets",()=>api.productMarkets(),["today","markets","macro"].includes(view));
  const macro=useReadModel("macro",()=>api.productMacro(),view==="macro"||commandOpen);
  const events=useReadModel("events",()=>api.productEvents(),["today","events","research"].includes(view)||commandOpen);
  const releases=events.data?.items??[];
  const selectedRelease=releases.find(r=>r.id===requestedRelease)??(!requestedRelease?preferredRelease(releases):null);
  const releaseId=requestedRelease??selectedRelease?.id??"";
  const eventDetail=useReadModel(`event:${releaseId}`,()=>api.productEvent(releaseId),view==="events"&&!!releaseId);
  const selectedDetail=eventDetail.data;
  const country=useReadModel(`country:${selectedCountryKey}:${selectedDimension??""}`,()=>api.productCountry(selectedCountryKey!,selectedDimension??undefined),view==="macro"&&!!selectedCountryKey);
  const selectedMarket=view==="markets"?markets.data?.items.find(i=>i.key===selectedMarketKey):null;

  function navigate(next:ProductView,params?:Record<string,string>) {
    const canonical=next==="today"?"radar":next==="research"?"memory":next;
    const query=new URLSearchParams(params);
    const hash=`#${canonical}${query.size?`?${query}`:""}`;
    if(window.location.hash!==hash) window.location.hash=hash;
    else setView(next);
  }
  function applyRoute() {
    const r=parseRoute(window.location.hash);setView(r.view);
    setRequestedRelease(r.params.get("release"));setSelectedMarketKey(r.params.get("asset"));
    setSelectedCountryKey(r.params.get("country"));setSelectedDimension(r.params.get("dimension"));
    setSelectedSeriesKey(r.params.get("series"));setSelectedThesis(r.params.get("thesis"));
    setToolsOpen(false);
  }
  const openEvent=(id:string)=>{if(view==="events"&&releaseId===id){eventDetail.refresh();events.refresh();}else navigate("events",{release:id});};
  const openMarket=(item:ProductMarketItem)=>navigate("markets",{asset:item.key});
  const openCountry=(item:ProductCountry,dimension?:string)=>navigate("macro",{country:item.key,...(dimension?{dimension}:{})});
  const openSeries=(key:string)=>navigate("macro",{series:key});
  const closeDrawer=()=>navigate(view);

  useEffect(()=>{
    window.addEventListener("hashchange",applyRoute);
    const external=(event:Event)=>navigate((event as CustomEvent<ProductView>).detail);
    window.addEventListener("worldstate:navigate",external);
    return ()=>{window.removeEventListener("hashchange",applyRoute);window.removeEventListener("worldstate:navigate",external);};
  },[]);
  useEffect(()=>{mainRef.current?.scrollTo({top:0});},[view]);
  useEffect(()=>{
    let active=true;
    const check=()=>void api.health().then(h=>{if(active){setHealth(h);setServiceError(null);}}).catch(e=>{if(active){setHealth(null);setServiceError(e instanceof Error?e.message:"服务暂时未连接");}});
    check();const interval=window.setInterval(check,30000);
    return ()=>{active=false;window.clearInterval(interval);};
  },[]);
  useEffect(()=>{
    if(!selectedSeriesKey||view!=="macro")return;
    let active=true;setSeriesDetail(null);setSeriesError(null);
    void api.seriesHistory(selectedSeriesKey).then(d=>{if(active)setSeriesDetail(d);}).catch(e=>{if(active)setSeriesError(e instanceof Error?e.message:"读取失败");});
    return ()=>{active=false;};
  },[view,selectedSeriesKey]);
  useEffect(()=>{
    const listener=(e:KeyboardEvent)=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();setCommandOpen(true);}if(e.key==="Escape"){setCommandOpen(false);setToolsOpen(false);}};
    window.addEventListener("keydown",listener);return()=>window.removeEventListener("keydown",listener);
  },[]);
  useEffect(()=>{
    const query=commandQuery.trim();if(query.length<2){setSearchEntities([]);return;}
    let active=true;
    const timer=window.setTimeout(()=>void api.series(query).then(items=>{if(active)setSearchEntities(items.slice(0,6).map(item=>{
      const key=String(item.canonical_key??item.key??item.id);
      return {key:`series:${key}`,label:String(item.title??key),note:"宏观序列",action:()=>openSeries(key)};
    }));}).catch(()=>{if(active)setSearchEntities([]);}),250);
    return()=>{active=false;clearTimeout(timer);};
  },[commandQuery]);
  const query=commandQuery.toLowerCase();
  const results:SearchResult[]=[
    ...NAV.map(n=>({key:n.key,label:n.label,note:n.note,action:()=>navigate(n.key)})),
    ...(markets.data?.items??[]).map(i=>({key:i.key,label:i.label,note:"市场",action:()=>openMarket(i)})),
    ...(macro.data?.countries??[]).map(i=>({key:i.key,label:i.label,note:"国家与宏观",action:()=>openCountry(i)})),
    ...releases.map(i=>({key:i.id,label:`${i.title} ${i.period_label}`,note:i.release_type,action:()=>openEvent(i.id)})),
  ].filter(i=>!query||`${i.label} ${i.note} ${i.key}`.toLowerCase().includes(query)).concat(searchEntities).slice(0,18);
  const toggle=(name:string,value:boolean,set:(v:boolean)=>void)=>{localStorage.setItem(name,value?"off":"on");set(!value);};
  const pageTitle=view==="macro"?"市场脉络":NAV.find(n=>n.key===view)?.label??(view==="data-control"?"数据源与连接":"方法与研究详情");
  const marketList=markets.data?.items??[];
  const refreshCurrent=()=>{if(view==="today"){markets.refresh();events.refresh();}else if(view==="markets")markets.refresh();else if(view==="macro")macro.refresh();else{events.refresh();eventDetail.refresh();}};

  return <div class={collapsed?"terminal-shell intelligence-shell terminal-shell--collapsed":"terminal-shell intelligence-shell"}>
    <aside class="sidebar"><div class="brand"><div class="brand__mark">W</div><div><strong>WorldState</strong><span>Personal intelligence</span></div></div><button type="button" class="shell-toggle" aria-label="收起侧栏" onClick={()=>toggle("worldstate.sidebar_collapsed",collapsed,setCollapsed)}>{collapsed?"→":"←"}</button>
      <nav aria-label="主导航">{NAV.map((n,i)=><button type="button" key={n.key} title={n.label} class={view===n.key||(n.key==="markets"&&view==="macro")?"nav-item nav-item--active":"nav-item"} onClick={()=>navigate(n.key)}><span class="nav-item__index">0{i+1}</span><span><strong>{n.label}</strong><small>{n.note}</small></span></button>)}</nav>
      <div class="shell-footer"><span>事件 → 定价 → 证据</span><button type="button" class="mode-toggle" onClick={()=>setToolsOpen(v=>!v)} aria-expanded={toolsOpen}>工具与设置</button>{toolsOpen?<div class="tools-menu"><button type="button" onClick={()=>navigate("data-control")}>数据源与连接</button><button type="button" onClick={()=>navigate("data-methods")}>方法与研究详情</button><button type="button" onClick={()=>toggle("worldstate.advanced_mode",advancedMode,setAdvancedMode)}>{advancedMode?"关闭高级模式":"开启高级模式"}</button></div>:null}</div>
    </aside>
    <main class="main" ref={mainRef}><header class="topbar"><strong>{pageTitle}</strong><div class="topbar__status"><button type="button" class="shell-command" onClick={()=>setCommandOpen(true)}>搜索市场、事件、序列 <kbd>Ctrl K</kbd></button><button type="button" class={learningMode?"mode-toggle mode-toggle--active":"mode-toggle"} onClick={()=>toggle("worldstate.learning_mode",learningMode,setLearningMode)}>{learningMode?"学习：开":"学习"}</button>{advancedMode?<Badge>高级</Badge>:null}<button type="button" class="mode-toggle" onClick={refreshCurrent}>刷新</button><span class={health?.database.status==="ok"?"connection-indicator ready":"connection-indicator"} title={serviceError??"服务状态不代表行情实时性"}>{health?.database.status==="ok"?"服务已连接":serviceError?"离线 · 保留记录":"连接中"}</span></div></header>
    <WorkspaceBoundary key={view}>
      {view==="today"?<><ReadStatus label="市场" resource={markets} advanced={advancedMode}/><ReadStatus label="事件" resource={events} advanced={advancedMode}/><RadarWorkspace markets={marketList} events={releases} onEvent={openEvent} onData={()=>navigate("data-control")} advanced={advancedMode} learningMode={learningMode}/></>:null}
      {view==="markets"||view==="macro"?<div class="context-navigation tabs-bar"><button type="button" class={view==="markets"?"active":""} onClick={()=>navigate("markets")}>跨资产市场</button><button type="button" class={view==="macro"?"active":""} onClick={()=>navigate("macro")}>全球宏观环境</button></div>:null}
      {view==="markets"?<><ReadStatus label="市场" resource={markets} advanced={advancedMode}/>{markets.data?<MarketsBoard items={marketList} onOpen={openMarket}/>:null}</>:null}
      {view==="macro"?<><ReadStatus label="宏观环境" resource={macro} advanced={advancedMode}/>{macro.data?<MacroBoard data={macro.data} selectedCountryKey={selectedCountryKey} learningMode={learningMode} onOpenCountry={openCountry}/>:null}</>:null}
      {view==="events"?<><ReadStatus label="事件列表" resource={events} advanced={advancedMode}/>{releaseId?<ReadStatus label="事件详情" resource={eventDetail} advanced={advancedMode}/>:null}<EventsBoard key={releaseId} releases={releases} selected={selectedRelease} detail={selectedDetail} learningMode={learningMode} onSelect={i=>openEvent(i.id)} onOpenLab={()=>undefined} onOpenDataSources={()=>navigate("data-control")} onOpenMarkets={()=>navigate("markets")}/></>:null}
      {view==="research"?<><ReadStatus label="事件档案" resource={events} advanced={advancedMode}/><MemoryWorkspace events={releases} onEvent={openEvent} selectedThesis={selectedThesis} onThesis={id=>navigate("research",{thesis:id})}/></>:null}
      {view==="data-control"?<DataControlWorkspace/>:null}{view==="data-methods"?<DataMethodsWorkspace/>:null}
    </WorkspaceBoundary></main>
    {selectedMarket?<Drawer title={selectedMarket.label} onClose={closeDrawer}><MarketInvestigation item={selectedMarket} markets={marketList} onOpen={openMarket} advanced={advancedMode} learningMode={learningMode}/></Drawer>:null}
    {view==="macro"&&selectedCountryKey?<Drawer title="宏观环境" onClose={closeDrawer}><ReadStatus label="国家" resource={country} advanced={advancedMode}/>{country.data?<CountryDrawerContent detail={country.data} advanced={advancedMode} learningMode={learningMode} onOpenMarket={openMarket} onOpenEvent={openEvent}/>:null}</Drawer>:null}
    {view==="macro"&&selectedSeriesKey?<Drawer title="宏观序列" onClose={closeDrawer}>{seriesDetail?<SeriesDrawerContent data={seriesDetail}/>:<p role="status">{seriesError??"正在读取序列…"}</p>}</Drawer>:null}
    {commandOpen?<div class="modal-backdrop" onClick={e=>{if(e.target===e.currentTarget)setCommandOpen(false);}}><section class="modal command-palette" role="dialog" aria-modal="true" aria-label="搜索 WorldState"><div class="modal__header"><h2>你想研究什么？</h2><button type="button" onClick={()=>setCommandOpen(false)}>关闭</button></div><div class="modal__body"><input autoFocus aria-label="搜索 WorldState" value={commandQuery} onInput={e=>setCommandQuery(e.currentTarget.value)} placeholder="黄金、CPI、中国、失业率…"/><div class="command-results">{results.map(r=><button type="button" key={r.key} onClick={()=>{r.action();setCommandOpen(false);setCommandQuery("");}}><strong>{r.label}</strong><span>{r.note}</span></button>)}{!results.length?<p>本地索引中没有匹配结果。</p>:null}</div></div></section></div>:null}
  </div>;
}
