import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Modal, Panel, StateMessage } from "../../components/Primitives";
import { ConceptStrip } from "../../components/ConceptHelp";
import type { ReleaseSummary } from "../../types";
import type { ConsensusCsvPreview, EventMinutePreview, ProductEventDetail } from "../../types/product";
import { fromLocalDateTimeInput, localTimeZoneLabel, toLocalDateTimeInput } from "../../utils/time";
import { EventLabWorkspace } from "../event-lab/EventLabWorkspace";

import { PreReleaseGuide, ReleaseReading } from "../intelligence/ReleaseReading";

type EventTab = "upcoming" | "recent" | "all";
type Dialog = "consensus" | "consensus-csv" | "minutes" | null;
type MappingKey = "timestamp" | "open" | "high" | "low" | "close" | "volume";

const WINDOW_LABELS: Record<string, string> = {
  post_1m: "1m",
  post_5m: "5m",
  post_15m: "15m",
  post_30m: "30m",
  post_60m: "1h",
};

const INDICATOR_LABELS: Record<string, string> = {
  headline_mom: "整体 CPI 月率",
  headline_yoy: "整体 CPI 年率",
  core_mom: "核心 CPI 月率",
  core_yoy: "核心 CPI 年率",
  headline_cpi_mom: "整体 CPI 月率",
  headline_cpi_yoy: "整体 CPI 年率",
  core_cpi_mom: "核心 CPI 月率",
  core_cpi_yoy: "核心 CPI 年率",
  payrolls: "非农就业人数",
  unemployment_rate: "失业率",
  average_hourly_earnings_mom: "平均时薪月率",
  average_hourly_earnings_yoy: "平均时薪年率",
  fed_funds_lower: "联邦基金目标下限",
  fed_funds_upper: "联邦基金目标上限",
  statement_tone_score: "声明立场",
  press_conference_tone_score: "新闻发布会立场",
};

function indicatorLabel(item: { key: string; label: string }): string {
  return INDICATOR_LABELS[item.key] ?? item.label;
}

function blockerLabel(value: string, detail: ProductEventDetail): string {
  const [code, keys = ""] = value.split(":", 2);
  const labels = keys.split(",").filter(Boolean).map((key) => {
    const indicator = detail.supported_indicators.find((item) => item.key === key);
    return indicator ? indicatorLabel(indicator) : INDICATOR_LABELS[key] ?? key;
  }).join("、");
  if (code === "missing_actual") return `缺少实际值${labels ? `：${labels}` : ""}`;
  if (code === "missing_pre_t0_consensus") return `缺少 T0 前市场预期${labels ? `：${labels}` : ""}`;
  if (code === "no_matched_indicator_actual_consensus") return "实际值与市场预期尚未形成可比较指标";
  if (code === "missing_eligible_event_minute_manifest") return "缺少合格的一分钟市场行情";
  return value;
}

function eventTone(item: ReleaseSummary): "good" | "warn" | "neutral" | "info" {
  if (item.analysis_status === "completed" && item.reproducibility_status === "complete") return "good";
  if (item.status === "scheduled") return "info";
  return "warn";
}

function eventType(value: string): string {
  if (value === "US_CPI") return "CPI";
  if (value === "US_NFP") return "NFP";
  return value;
}

function countryLabel(value: string): string {
  return { USA: "美国", CHN: "中国", JPN: "日本", GBR: "英国", EA19: "欧元区" }[value] ?? value;
}

function dateLabel(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeLabel(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function numberLabel(value: number | null | undefined, unit?: string): string {
  if (value == null) return "—";
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit === "%" ? "%" : unit ? ` ${unit}` : ""}`;
}

function surpriseDirectionLabel(value: string | null | undefined): string {
  return {
    hot: "偏热",
    cold: "偏冷",
    in_line: "符合预期",
    mixed: "分化",
    neutral: "中性",
  }[value ?? ""] ?? value ?? "—";
}

function statusLabel(value: string): string {
  return {
    scheduled: "即将发布",
    released: "已发布",
    eligible: "可用于分析",
    partial: "部分覆盖",
    ineligible: "不可用于分析",
    available: "可用",
    missing: "缺失",
    pre_t0: "T0 前快照",
  }[value] ?? value;
}

function reactionTone(status: string): "good" | "warn" | "neutral" {
  return status === "available" || status === "eligible" ? "good" : status === "partial" ? "warn" : "neutral";
}

function csvHeaders(text: string): string[] {
  const first = text.split(/\r?\n/, 1)[0] ?? "";
  return first.split(",").map((value) => value.trim()).filter(Boolean);
}

function WorkflowSection({ title, eyebrow, children }: { title: string; eyebrow: string; children: ComponentChildren }) {
  return <section class="event-workflow__section"><div class="event-workflow__heading"><span>{eyebrow}</span><h2>{title}</h2></div>{children}</section>;
}

export function EventsBoard({
  releases,
  selected,
  detail,
  onSelect,
  onOpenLab,
  onOpenDataSources,
  onOpenMarkets,
  learningMode = false,
}: {
  releases: ReleaseSummary[];
  selected: ReleaseSummary | null;
  detail: ProductEventDetail | null;
  onSelect: (release: ReleaseSummary) => void;
  onOpenLab: () => void;
  onOpenDataSources: () => void;
  onOpenMarkets?: () => void;
  learningMode?: boolean;
}) {
  onOpenMarkets ??= () =>
    window.dispatchEvent(new CustomEvent("worldstate:navigate", { detail: "markets" }));
  const [labOpen, setLabOpen] = useState(false);
  const [readingTab, setReadingTab] = useState("difference");
  const [eventSearch, setEventSearch] = useState("");
  const analysisKey = useRef(crypto.randomUUID());
  const [analysisBusy,setAnalysisBusy] = useState(false);
  const [analysisError,setAnalysisError] = useState<string|null>(null);
  const [eventTab, setEventTab] = useState<EventTab>("recent");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [indicatorKey, setIndicatorKey] = useState("");
  const [consensusValue, setConsensusValue] = useState("");
  const [capturedAt, setCapturedAt] = useState(toLocalDateTimeInput());
  const [sourceName, setSourceName] = useState("手工记录的市场预期");
  const [sourceUrl, setSourceUrl] = useState("");
  const [verificationNotes, setVerificationNotes] = useState("");

  const [consensusCsv, setConsensusCsv] = useState("");
  const [consensusPreview, setConsensusPreview] = useState<ConsensusCsvPreview | null>(null);

  const [minuteStep, setMinuteStep] = useState(1);
  const [minuteAsset, setMinuteAsset] = useState("");
  const [minuteFileName, setMinuteFileName] = useState("");
  const [minuteCsv, setMinuteCsv] = useState("");
  const [minuteTimezone, setMinuteTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [minuteVerified, setMinuteVerified] = useState(false);
  const [minuteSourceUrl, setMinuteSourceUrl] = useState("");
  const [minuteMapping, setMinuteMapping] = useState<Record<MappingKey, string>>({ timestamp: "timestamp", open: "open", high: "high", low: "low", close: "close", volume: "volume" });
  const [minutePreview, setMinutePreview] = useState<EventMinutePreview | null>(null);

  useEffect(() => {
    if (!selected) return;
    setEventTab(selected.status === "scheduled" ? "upcoming" : "recent");
  }, [selected?.id]);

  const visibleReleases = useMemo(() => {
    const visible = eventTab === "all"
      ? [...releases]
      : releases.filter((item) => eventTab === "recent" ? item.status === "released" : item.status === "scheduled" && Date.parse(item.scheduled_at) >= Date.now());
    return visible.filter(item => `${item.title} ${item.release_type} ${item.period_label}`.toLowerCase().includes(eventSearch.toLowerCase())).sort((left, right) => {
      const delta = new Date(left.scheduled_at).getTime() - new Date(right.scheduled_at).getTime();
      return eventTab === "upcoming" ? delta : -delta;
    }).slice(0, eventTab === "all" ? 100 : 12);
  }, [eventTab, releases, eventSearch]);

  const availableAssets = useMemo(() => {
    if (!detail) return [];
    return [...detail.market_reaction.available_assets, ...detail.market_reaction.partial_assets, ...detail.market_reaction.missing_assets]
      .filter((item, index, rows) => rows.findIndex((candidate) => candidate.key === item.key) === index);
  }, [detail]);

  function refreshDetail() {
    if (selected) onSelect(selected);
  }

  async function runAnalysis() {
    if (!detail?.actions.can_run_analysis || analysisBusy) return;
    setAnalysisBusy(true);setAnalysisError(null);
    try { await api.analyzeRelease(detail.id,analysisKey.current);refreshDetail(); }
    catch(error) {setAnalysisError(error instanceof Error?error.message:"分析未完成，请重试。原始输入没有被修改。");}
    finally {setAnalysisBusy(false);}
  }

  function openConsensus() {
    const first = detail?.supported_indicators[0];
    setIndicatorKey(first?.key ?? "");
    setConsensusValue("");
    setCapturedAt(toLocalDateTimeInput());
    setFormError(null);
    setDialog("consensus");
  }

  function openConsensusCsv() {
    setConsensusCsv("");
    setConsensusPreview(null);
    setFormError(null);
    setDialog("consensus-csv");
  }

  function openMinuteWizard() {
    setMinuteStep(2);
    setMinuteAsset(availableAssets[0]?.key ?? "gold_gc");
    setMinuteFileName("");
    setMinuteCsv("");
    setMinutePreview(null);
    setFormError(null);
    setDialog("minutes");
  }

  async function saveConsensus(event: Event) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true); setFormError(null);
    try {
      await api.appendConsensus(selected.id, {
        indicator_key: indicatorKey,
        consensus_value: Number(consensusValue),
        source_name: sourceName.trim() || "手工记录的市场预期",
        source_url: sourceUrl.trim() || undefined,
        captured_at: fromLocalDateTimeInput(capturedAt),
        quality_grade: "C",
        is_manual: true,
        verification_notes: verificationNotes.trim() || undefined,
      });
      setDialog(null);
      refreshDetail();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "保存失败，请确认时间早于事件发布时刻。");
    } finally { setBusy(false); }
  }

  async function previewConsensusFile() {
    if (!selected || !consensusCsv) return;
    setBusy(true); setFormError(null);
    try { setConsensusPreview(await api.previewConsensusCsv(selected.id, consensusCsv)); }
    catch (error) { setFormError(error instanceof Error ? error.message : "CSV 预检失败。"); }
    finally { setBusy(false); }
  }

  async function confirmConsensusFile() {
    if (!selected || !consensusPreview?.can_confirm) return;
    setBusy(true); setFormError(null);
    try {
      await api.importConsensusCsv(selected.id, consensusCsv);
      setDialog(null);
      refreshDetail();
    } catch (error) { setFormError(error instanceof Error ? error.message : "CSV 导入失败。"); }
    finally { setBusy(false); }
  }

  async function readMinuteFile(file: File | null) {
    if (!file) return;
    const text = await file.text();
    setMinuteFileName(file.name);
    setMinuteCsv(text);
    const headers = csvHeaders(text);
    setMinuteMapping((current) => Object.fromEntries(Object.entries(current).map(([key, value]) => [key, headers.includes(value) ? value : headers.find((header) => header.toLowerCase() === key) ?? value])) as Record<MappingKey, string>);
    setMinuteStep(3);
  }

  async function previewMinutes() {
    if (!selected || !minuteCsv) return;
    setBusy(true); setFormError(null);
    try {
      const preview = await api.previewMarketBars(selected.id, {
        instrument_key: minuteAsset,
        csv_text: minuteCsv,
        provider_key: "manual_csv",
        source_name: minuteFileName || "手工分钟行情 CSV",
        source_url: minuteSourceUrl.trim() || undefined,
        verified: minuteVerified,
        is_fixture: false,
        timezone: minuteTimezone,
        column_mapping: minuteMapping,
      });
      setMinutePreview(preview);
      setMinuteStep(7);
    } catch (error) { setFormError(error instanceof Error ? error.message : "分钟行情预检失败。"); }
    finally { setBusy(false); }
  }

  async function importMinutes() {
    if (!selected || !minutePreview) return;
    setBusy(true); setFormError(null);
    try {
      await api.importMarketBars(selected.id, {
        instrument_key: minuteAsset,
        csv_text: minuteCsv,
        provider_key: "manual_csv",
        source_name: minuteFileName || "手工分钟行情 CSV",
        source_url: minuteSourceUrl.trim() || undefined,
        verified: minuteVerified,
        is_fixture: false,
        timezone: minuteTimezone,
        column_mapping: minuteMapping,
      });
      setMinuteStep(8);
      refreshDetail();
    } catch (error) { setFormError(error instanceof Error ? error.message : "分钟行情导入失败。"); }
    finally { setBusy(false); }
  }

  if (!releases.length) return <StateMessage title="暂无宏观事件" detail="请先加载官方事件日历。" action={<button type="button" class="button-primary" onClick={onOpenDataSources}>打开数据源</button>} />;
  if (labOpen && selected) return <div class="workspace workspace--product"><button type="button" class="button-secondary" onClick={() => setLabOpen(false)}>← 返回事件工作流</button><EventLabWorkspace release={selected} onRefresh={async () => undefined} /></div>;

  return (
    <div class="workspace workspace--product">

      <div class="events-layout events-layout--research">
        <aside class="event-rail"><div class="section-heading"><h2>事件时间线</h2><small>本机时区</small></div>
          <input aria-label="查找事件" placeholder="CPI、非农、月份…" value={eventSearch} onInput={e=>setEventSearch(e.currentTarget.value)}/>
          <div class="tabs-bar" role="tablist">{(["upcoming","recent","all"] as EventTab[]).map(tab=><button type="button" key={tab} class={eventTab===tab?"active":""} onClick={()=>setEventTab(tab)} role="tab" aria-selected={eventTab===tab}>{tab==="recent"?"已发布":tab==="upcoming"?"待发布":"全部"}</button>)}</div>
          <div class="event-list">{visibleReleases.map(item=><button type="button" class={selected?.id===item.id?"event-calendar__item event-list__row--active":"event-calendar__item"} key={item.id} onClick={()=>{setLabOpen(false);onSelect(item);}}><span class="event-list__date">{dateLabel(item.scheduled_at)}</span><span><strong>{eventType(item.release_type)}</strong><small>{timeLabel(item.scheduled_at)} · {item.period_label}</small></span></button>)}</div>
          {!visibleReleases.length?<div class="inline-empty"><p>本地没有匹配事件。</p><button type="button" onClick={onOpenDataSources}>检查日历来源 →</button></div>:null}
        </aside>
        <section class="event-reading">
          {!detail?<div class="inline-empty"><h2>{selected?"正在读取这个事件":"选择事件开始研究"}</h2><p>右侧保留完整的预期 → 数据 → 市场反应链。</p></div>:<>
            <header class="event-reading-head"><div><span class="section-label">{countryLabel(detail.event.country)} · {detail.event.period_label}</span><h1>{detail.event.title}</h1><time>{new Date(detail.event.scheduled_at).toLocaleString()} · {localTimeZoneLabel()}</time></div><Badge tone={detail.event.status==="released"?"info":"neutral"}>{statusLabel(detail.event.status)}</Badge></header>
            <div class="event-takeaway"><span>数据告诉我们</span><strong>{detail.surprise.available?detail.surprise.classification??surpriseDirectionLabel(detail.surprise.direction):detail.actual.available?"实际值已到，事前预期尚未齐备":"等待正式发布"}</strong><p>{detail.surprise.available?"先看哪些指标偏离预期，再核对市场是否按同一条路径反应。":detail.event.status==="scheduled"?"发布前先记录市场预期；发布后的实际值不会被提前填入。":"打开来源核对已有数据，缺少的输入不会被估算填满。"}</p></div>
            <div class="event-progress"><span class={detail.expectations.eligible_count?"done":""}>① 事前预期 {detail.expectations.eligible_count?detail.expectations.eligible_count+" 项":"未齐"}</span><span class={detail.actual.available?"done":""}>② 实际值 {detail.actual.available?"已获取":"待发布 / 获取"}</span><span class={detail.market_reaction.available?"done":""}>③ 市场反应 {detail.market_reaction.available?"可查看":"待补齐"}</span><span class={detail.analysis.run_id?"done":""}>④ 复盘 {detail.analysis.run_id?"已有记录":"尚未形成"}</span></div>
            <div class="tabs-bar event-reading-tabs">{[["difference","预期差"],["reaction","跨资产反应"],["interpretation","解释与历史"],["sources","来源与详情"]].map(([key,label])=><button type="button" key={key} class={readingTab===key?"active":""} onClick={()=>setReadingTab(key!)}>{label}</button>)}</div>
            {readingTab==="difference"?<>
              <ConceptStrip concepts={["consensus","surprise","revision"]} active={learningMode}/>
              {detail.event.status==="scheduled"?<PreReleaseGuide type={detail.event.type}/>:null}
              <div class="table-wrap"><table class="event-comparison"><thead><tr><th>指标</th><th>事前预期</th><th>实际</th><th>偏离预期</th><th>前值 / 修正</th></tr></thead><tbody>{detail.supported_indicators.map(indicator=>{
                const expectation=detail.expectations.indicators.find(i=>i.key===indicator.key);
                const actual=detail.actual.indicators.find(i=>i.key===indicator.key);
                const surprise=detail.surprise.indicators.find(i=>i.key===indicator.key);
                return <tr key={indicator.key}><th>{indicatorLabel(indicator)}<small>{indicator.unit}</small></th><td>{numberLabel(expectation?.consensus,indicator.unit)}{expectation?.consensus!=null&&expectation.eligibility!=="pre_t0"?<small>仅供参考 / 未通过校验</small>:null}</td><td class="actual-value">{numberLabel(actual?.actual,indicator.unit)}</td><td>{surprise?.raw_surprise==null?"—":<><span>{numberLabel(surprise.raw_surprise,indicator.unit==="%"?"百分点":indicator.unit)}</span><small>{surpriseDirectionLabel(surprise.direction)}</small></>}</td><td>{numberLabel(actual?.previous,indicator.unit)}{actual?.revised_previous!=null?<small>修正为 {numberLabel(actual.revised_previous,indicator.unit)}</small>:null}</td></tr>;
              })}</tbody></table></div>
              <div class="workflow-actions"><button type="button" class="button-secondary" onClick={openConsensus}>添加预期记录</button><button type="button" class="button-secondary" onClick={openConsensusCsv}>导入预期 CSV</button><button type="button" class="button-primary" onClick={()=>setReadingTab("reaction")}>继续看市场反应 →</button></div>
              <DetailsDisclosure label="惊喜尺度与样本限制"><p>偏离预期不是行情预测。Z-score 仅在历史样本满足方法要求时提供；阈值尺度不是 Z-score。</p>{detail.surprise.indicators.map(i=><div class="research-row" key={i.key}><strong>{indicatorLabel(i)}</strong><span>{i.surprise_z==null?`Z 不可用 · 样本 ${i.sample_count??0} · 阈值尺度 ${numberLabel(i.threshold_scaled_surprise)}`:`Z ${numberLabel(i.surprise_z)} · 样本 ${i.sample_count}`}</span></div>)}</DetailsDisclosure>
            </>:null}
            {readingTab==="reaction"?<>
              <div class="section-heading"><h2>谁先动，谁在确认？</h2><span>事件发布后的窗口</span></div>
              {detail.market_reaction.matrix.length?<div class="reaction-table"><div class="reaction-table__head"><span>资产</span>{Object.values(WINDOW_LABELS).map(label=><span key={label}>{label}</span>)}</div>{detail.market_reaction.matrix.map(row=><div class="reaction-table__row" key={row.instrument_key+row.stage_key}><strong>{row.instrument_label}{row.is_proxy?<small>代理</small>:null}<small>{row.stage_key}</small></strong>{Object.keys(WINDOW_LABELS).map(key=>{const p=row.windows[key];return <span key={key} class={p?.reversal?"reaction-cell reaction-cell--reversal":"reaction-cell"} title={p?.missing_reason??undefined}>{p?.value==null?"—":`${p.value>0?"+":""}${p.value.toFixed(2)} ${p.unit}`}{p?.coverage!=null?<small>覆盖 {Math.round(p.coverage*100)}%</small>:null}{p?.reversal?<small>方向反转</small>:null}</span>;})}</div>)}</div>:<div class="minute-gap"><span class="gap-icon">↗</span><div><h3>还不能解释发布后的短时反应</h3><p>缺少合格分钟行情。日线不能代替 1m / 5m / 15m / 30m / 1h 反应，也无法判断谁先动。</p><div class="workflow-actions"><button type="button" class="button-primary" onClick={openMinuteWizard}>导入分钟行情</button><button type="button" class="button-secondary" onClick={onOpenMarkets}>查看日线背景</button></div></div></div>}
              {detail.market_reaction.partial_assets.length?<p class="inline-notice">部分覆盖：{detail.market_reaction.partial_assets.map(i=>i.label).join("、")}。尚未满足研究条件。</p>:null}
              <DetailsDisclosure label="资产覆盖与代理身份"><div class="asset-status-grid">{availableAssets.map(i=><div key={i.key}><strong>{i.label}</strong><Badge tone={i.eligible?"info":"warn"}>{i.eligible?"可用于分析":statusLabel(i.status??"missing")}</Badge>{i.is_proxy?<small>代理：{i.proxy_for}</small>:null}</div>)}</div></DetailsDisclosure>
            </>:null}
            {readingTab==="interpretation"?<>
              <div class="section-heading"><h2>市场在交易什么？</h2></div>
              {detail.analysis.run_id?<><ReleaseReading releaseId={detail.id} runId={detail.analysis.run_id} onEvent={id=>{const item=releases.find(r=>r.id===id);if(item)onSelect(item);}}/><p>已有研究记录 · 置信度 {detail.analysis.confidence==null?"未记录":Math.round(detail.analysis.confidence*100)+"%"} · {detail.analysis.reproducibility==="complete"?"可复现输入已保存":"复现状态待核验"}</p><button type="button" class="button-primary" onClick={()=>{setLabOpen(true);onOpenLab();}}>阅读证据、竞争解释与历史案例 →</button></>:<div class="inline-empty"><h3>尚未形成有证据约束的复盘</h3><p>目前不能根据数据惊喜直接断言市场原因，也没有可显示的本次历史百分位。</p><ul>{detail.actions.analysis_blockers.map(b=><li key={b}>{blockerLabel(b,detail)}</li>)}</ul>{detail.actions.can_run_analysis?<button type="button" class="button-primary" disabled={analysisBusy} onClick={()=>void runAnalysis()}>{analysisBusy?"正在生成复盘…":"生成本次复盘"}</button>:<button type="button" class="button-primary" onClick={()=>setReadingTab("reaction")}>补齐市场反应 →</button>}</div>}
              {analysisError?<p class="inline-notice" role="alert">{analysisError}</p>:null}
              {detail.analysis.data_gaps.length?<DetailsDisclosure label="本次分析的数据缺口"><ul>{detail.analysis.data_gaps.map(g=><li key={g}>{g}</li>)}</ul></DetailsDisclosure>:null}
            </>:null}
            {readingTab==="sources"?<>
              <h2>来源与记录时间</h2><div class="source-records">{detail.expectations.indicators.map(i=><div key={i.key}><strong>{indicatorLabel(i)} · 预期</strong><span>{i.source??"未记录来源"}</span><time>{i.captured_at?new Date(i.captured_at).toLocaleString():"未记录采集时间"}</time></div>)}{detail.actual.indicators.map(i=><div key={i.key}><strong>{indicatorLabel(i)} · 实际</strong><span>{i.source??"未记录来源"}</span></div>)}</div>
              <p>事件时间：{detail.event.scheduled_at} · 原始时区：{detail.event.source_timezone}</p>
              <DetailsDisclosure label="高级研究详情"><pre class="json-view">{JSON.stringify({source:detail.source,provenance:detail.data_provenance,quality:detail.data_quality,contamination:detail.contamination,analysis:detail.analysis},null,2)}</pre></DetailsDisclosure>
            </>:null}
          </>}
        </section>
      </div>

      {dialog === "consensus" && detail ? <Modal title={`添加市场预期 · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><form class="form-stack" onSubmit={saveConsensus}><label>指标<select required value={indicatorKey} onChange={(event) => setIndicatorKey(event.currentTarget.value)}>{detail.supported_indicators.map((item) => <option value={item.key}>{indicatorLabel(item)} · {item.unit}</option>)}</select></label><label>Consensus<input required type="number" step="any" value={consensusValue} onInput={(event) => setConsensusValue(event.currentTarget.value)} /></label><label>Captured At · {localTimeZoneLabel()}<input required type="datetime-local" value={capturedAt} onInput={(event) => setCapturedAt(event.currentTarget.value)} /><small>保存时转换为 UTC；后端严格验证 Captured At &lt; T0。</small></label><label>来源<input required value={sourceName} onInput={(event) => setSourceName(event.currentTarget.value)} /></label><DetailsDisclosure label="高级信息"><label>来源链接<input type="url" value={sourceUrl} onInput={(event) => setSourceUrl(event.currentTarget.value)} /></label><label>核验说明<textarea value={verificationNotes} onInput={(event) => setVerificationNotes(event.currentTarget.value)} /></label></DetailsDisclosure>{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>取消</button><button type="submit" class="button-primary" disabled={busy}>{busy ? "保存中…" : "保存预期"}</button></div></form></Modal> : null}

      {dialog === "consensus-csv" && detail ? <Modal title={`批量导入 Consensus · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><div class="form-stack"><label>CSV 文件<input type="file" accept=".csv,text/csv" onChange={async (event) => { const file = event.currentTarget.files?.[0]; if (file) { setConsensusCsv(await file.text()); setConsensusPreview(null); } }} /></label><p class="method-note">字段：indicator_key, consensus_value, captured_at, source_name。Captured At 必须包含时区。</p>{consensusPreview ? <><div class="import-summary"><Badge tone="good">{consensusPreview.summary.eligible} 可导入</Badge><Badge tone="warn">{consensusPreview.summary.post_t0} Post-T0</Badge><Badge tone="neutral">{consensusPreview.summary.unknown_indicator} 未知指标</Badge><Badge tone="neutral">{consensusPreview.summary.invalid} 无效</Badge></div><div class="preview-table">{consensusPreview.items.slice(0, 20).map((item) => <div><strong>{item.indicator_label}</strong><span>{item.consensus_value}</span><span>{new Date(item.captured_at).toLocaleString()}</span><Badge tone={item.eligible ? "good" : "warn"}>{statusLabel(item.status)}</Badge></div>)}</div></> : null}{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>取消</button>{!consensusPreview ? <button type="button" class="button-primary" disabled={!consensusCsv || busy} onClick={() => void previewConsensusFile()}>{busy ? "检查中…" : "预览并验证"}</button> : <button type="button" class="button-primary" disabled={!consensusPreview.can_confirm || busy} onClick={() => void confirmConsensusFile()}>{busy ? "导入中…" : `确认导入 ${consensusPreview.summary.eligible} 条`}</button>}</div></div></Modal> : null}

      {dialog === "minutes" && detail ? <Modal title={`分钟行情导入 · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><div class="wizard-progress">{["事件", "资产", "文件", "列映射", "时区", "验证", "预览", "导入"].map((label, index) => <span class={minuteStep >= index + 1 ? "active" : ""}><b>{index + 1}</b>{label}</span>)}</div><div class="form-stack"><div class="wizard-context"><span>事件</span><strong>{detail.event.title} · {new Date(detail.event.scheduled_at).toLocaleString()}</strong></div>{minuteStep >= 2 ? <label>资产<select value={minuteAsset} onChange={(event) => { setMinuteAsset(event.currentTarget.value); setMinuteStep(2); setMinutePreview(null); }}>{availableAssets.map((item) => <option value={item.key}>{item.label}{item.is_proxy ? "（代理）" : ""}</option>)}</select></label> : null}{minuteStep >= 2 ? <label>CSV 文件<input type="file" accept=".csv,text/csv" onChange={(event) => void readMinuteFile(event.currentTarget.files?.[0] ?? null)} /></label> : null}{minuteStep >= 3 && minuteCsv ? <><div class="column-mapping"><strong>列映射</strong>{(["timestamp", "open", "high", "low", "close", "volume"] as MappingKey[]).map((key) => <label>{key}<select value={minuteMapping[key]} onChange={(event) => setMinuteMapping({ ...minuteMapping, [key]: event.currentTarget.value })}>{csvHeaders(minuteCsv).map((header) => <option value={header}>{header}</option>)}</select></label>)}</div><label>原始时间所用时区<input value={minuteTimezone} onInput={(event) => setMinuteTimezone(event.currentTarget.value)} /><small>例如 UTC、America/New_York、Asia/Shanghai。带时区的时间戳仍按自身时区解析。</small></label><label>来源链接<input type="url" value={minuteSourceUrl} onInput={(event) => setMinuteSourceUrl(event.currentTarget.value)} /></label><label class="check-row"><input type="checkbox" checked={minuteVerified} onChange={(event) => setMinuteVerified(event.currentTarget.checked)} />我已核验文件来源和资产身份</label></> : null}{minutePreview ? <><div class="eligibility-card"><Badge tone={reactionTone(minutePreview.eligibility.status)}>{statusLabel(minutePreview.eligibility.status)}</Badge><strong>{minutePreview.eligibility.bar_count} bars · T-{minutePreview.eligibility.pre_event_minutes}m 至 T+{minutePreview.eligibility.post_event_minutes}m</strong><span>一分钟频率 {Math.round(minutePreview.eligibility.one_minute_interval_ratio * 100)}% · 缺失 {minutePreview.eligibility.missing_bar_count}</span><ul>{[...minutePreview.eligibility.reasons, ...minutePreview.eligibility.limitations].map((item) => <li>{item}</li>)}</ul></div><div class="preview-table">{minutePreview.preview.slice(0, 8).map((item) => <div><strong>{new Date(item.timestamp).toLocaleString()}</strong><span>O {item.open}</span><span>C {item.close}</span></div>)}</div></> : null}{minuteStep === 8 ? <StateMessage title="分钟数据已存储" detail={minutePreview?.eligibility.eligible ? "该数据已通过 Eligibility，可供下一次 AnalysisRun 使用。" : "数据已保留，但未通过 Eligibility，不会进入 Event Engine。"} /> : null}{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>{minuteStep === 8 ? "完成" : "取消"}</button>{minuteCsv && !minutePreview ? <button type="button" class="button-primary" disabled={busy} onClick={() => void previewMinutes()}>{busy ? "验证中…" : "验证并预览"}</button> : null}{minutePreview && minuteStep < 8 ? <button type="button" class="button-primary" disabled={busy} onClick={() => void importMinutes()}>{busy ? "导入中…" : minutePreview.eligibility.eligible ? "确认导入" : "存储但不用于分析"}</button> : null}</div></div></Modal> : null}
    </div>
  );
}
