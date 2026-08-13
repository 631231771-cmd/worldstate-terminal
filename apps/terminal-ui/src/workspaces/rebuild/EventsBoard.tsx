import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Modal, Panel, StateMessage } from "../../components/Primitives";
import { ConceptStrip } from "../../components/ConceptHelp";
import type { ReleaseSummary } from "../../types";
import type { ConsensusCsvPreview, EventMinutePreview, ProductEventDetail } from "../../types/product";
import { fromLocalDateTimeInput, localTimeZoneLabel, toLocalDateTimeInput } from "../../utils/time";
import { EventLabWorkspace } from "../event-lab/EventLabWorkspace";

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
      : releases.filter((item) => eventTab === "recent" ? item.status === "released" : item.status === "scheduled");
    return visible.sort((left, right) => {
      const delta = new Date(left.scheduled_at).getTime() - new Date(right.scheduled_at).getTime();
      return eventTab === "upcoming" ? delta : -delta;
    }).slice(0, eventTab === "all" ? 100 : 12);
  }, [eventTab, releases]);

  const availableAssets = useMemo(() => {
    if (!detail) return [];
    return [...detail.market_reaction.available_assets, ...detail.market_reaction.partial_assets, ...detail.market_reaction.missing_assets]
      .filter((item, index, rows) => rows.findIndex((candidate) => candidate.key === item.key) === index);
  }, [detail]);

  function refreshDetail() {
    if (selected) onSelect(selected);
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
      <section class="page-heading page-heading--compact"><div><div class="eyebrow">EVENT RESEARCH</div><h1>宏观事件研究</h1><p>从预期、实际值和修订开始，沿着 Surprise、市场反应、历史背景与证据逐层阅读。</p><ConceptStrip concepts={["consensus", "surprise", "revision", "reversal"]} active={learningMode} /></div><div class="page-heading__aside"><Badge tone="info">{releases.length} 个事件</Badge></div></section>
      <div class="events-layout events-layout--research">
        <Panel title="事件" eyebrow="CALENDAR">
          <div class="tabs-bar" role="tablist">{(["upcoming", "recent", "all"] as EventTab[]).map((tab) => <button type="button" class={eventTab === tab ? "active" : ""} onClick={() => setEventTab(tab)} role="tab" aria-selected={eventTab === tab}>{tab === "recent" ? "近期发布" : tab === "upcoming" ? "当前 / 即将" : "全部"}</button>)}</div>
          <div class="event-list">{visibleReleases.map((item) => <button type="button" class={selected?.id === item.id ? "event-calendar__item event-list__row--active" : "event-calendar__item"} key={item.id} onClick={() => { setLabOpen(false); onSelect(item); }}><span class="event-list__date">{dateLabel(item.scheduled_at)}</span><span><strong>{eventType(item.release_type)}</strong><small>{timeLabel(item.scheduled_at)} · {item.period_label}</small></span><Badge tone={eventTone(item)}>{statusLabel(item.status)}</Badge></button>)}</div>
        </Panel>

        <Panel title={detail ? `${eventType(detail.event.type)} · ${detail.event.period_label}` : "选择事件"} eyebrow="RESEARCH WORKFLOW">
          {!detail ? <div class="empty-action"><div><h3>选择一个事件开始研究</h3><p>系统优先显示最近已发布的事件。</p></div></div> : <div class="event-workflow">
            <WorkflowSection title="事件概览" eyebrow="OVERVIEW"><div class="event-detail__headline"><div><strong>{detail.event.title}</strong><span>{new Date(detail.event.scheduled_at).toLocaleString()} · {countryLabel(detail.event.country)}</span></div><Badge tone={reactionTone(detail.event.status === "released" ? "available" : "partial")}>{statusLabel(detail.event.status)}</Badge></div><div class="event-readiness"><div class={detail.actual.available ? "ready" : "missing"}><span>实际值</span><strong>{detail.actual.available ? "已获取" : "待获取"}</strong></div><div class={detail.expectations.available ? "ready" : "missing"}><span>事前预期</span><strong>{detail.expectations.eligible_count ? `${detail.expectations.eligible_count} 项可用` : "待补充"}</strong></div><div class={detail.market_reaction.available ? "ready" : "missing"}><span>分钟行情</span><strong>{detail.market_reaction.available ? "可分析" : "待导入"}</strong></div></div>{detail.actions.analysis_blockers.length ? <ul class="workflow-blocker-list">{detail.actions.analysis_blockers.map((item) => <li key={item}>{blockerLabel(item, detail)}</li>)}</ul> : <Badge tone="good">研究输入已齐备</Badge>}</WorkflowSection>

            <WorkflowSection title="市场预期" eyebrow="EXPECTATIONS"><div class="event-indicator-table"><div class="event-indicator-table__head"><span>指标</span><span>Consensus</span><span>记录时间</span><span>来源</span></div>{detail.expectations.indicators.map((item) => <div class="event-indicator-table__row"><strong>{indicatorLabel(item)}<small>{item.unit}</small></strong><span>{numberLabel(item.consensus, item.unit)}</span><span>{item.captured_at ? new Date(item.captured_at).toLocaleString() : "—"}</span><span>{item.source ?? "—"}</span></div>)}</div><div class="workflow-actions"><button type="button" class="button-primary" onClick={openConsensus}>添加预期</button><button type="button" class="button-secondary" onClick={openConsensusCsv}>批量导入 CSV</button></div></WorkflowSection>

            <WorkflowSection title="实际值与修订" eyebrow="ACTUAL / REVISION"><div class="event-indicator-table"><div class="event-indicator-table__head"><span>指标</span><span>Actual</span><span>Previous</span><span>Revision</span></div>{detail.actual.indicators.map((item) => <div class="event-indicator-table__row"><strong>{indicatorLabel(item)}<small>{item.unit}</small></strong><span>{numberLabel(item.actual, item.unit)}</span><span>{numberLabel(item.previous, item.unit)}</span><span>{numberLabel(item.revision, item.unit)}</span></div>)}</div></WorkflowSection>

            <WorkflowSection title="数据惊喜" eyebrow="SURPRISE">{detail.surprise.available ? <><div class="event-summary-strip"><div><span>综合分类</span><strong>{detail.surprise.classification ?? "未分类"}</strong></div><div><span>综合分数</span><strong>{numberLabel(detail.surprise.score)}</strong></div><div><span>方向</span><strong>{surpriseDirectionLabel(detail.surprise.direction)}</strong></div></div><div class="event-indicator-table event-indicator-table--compact">{detail.surprise.indicators.map((item) => <div class="event-indicator-table__row"><strong>{indicatorLabel(item)}</strong><span>原始 {numberLabel(item.raw_surprise)}</span><span>{item.surprise_z == null ? `阈值尺度 ${numberLabel(item.threshold_scaled_surprise)}` : `Z ${numberLabel(item.surprise_z)}`}</span><span title={item.z_score_unavailable_reason ?? undefined}>{item.surprise_z == null ? `Z 样本不足（${item.sample_count ?? 0}）` : `Z 样本 ${item.sample_count ?? "—"}`}</span></div>)}</div></> : <div class="empty-action"><div><h3>暂不能计算 Surprise</h3><p>需要 Actual 和严格早于 T0 的 Consensus。</p></div><button type="button" class="button-primary" onClick={openConsensus}>添加预期</button></div>}</WorkflowSection>

            <WorkflowSection title="市场反应" eyebrow="MARKET REACTION">{detail.market_reaction.available ? <div class="reaction-table"><div class="reaction-table__head"><span>资产</span>{Object.values(WINDOW_LABELS).map((label) => <span>{label}</span>)}</div>{detail.market_reaction.matrix.map((row) => <div class="reaction-table__row"><strong>{row.instrument_label}{row.is_proxy ? <small>代理</small> : null}</strong>{Object.keys(WINDOW_LABELS).map((key) => { const point = row.windows[key]; return <span class={point?.reversal ? "reaction-cell reaction-cell--reversal" : "reaction-cell"}>{point?.value == null ? "—" : `${point.value > 0 ? "+" : ""}${point.value.toFixed(2)} ${point.unit}`}</span>; })}</div>)}</div> : <div class="empty-action empty-action--compact"><div><h3>暂无合格分钟行情</h3><p>当前日线数据只能说明当日市场环境，不能判断发布后 1m–1h 的短时反应。</p></div><div class="workflow-actions"><button type="button" class="button-primary" onClick={openMinuteWizard}>导入分钟数据</button><button type="button" class="button-secondary" onClick={onOpenMarkets}>查看日线市场</button></div></div>}{detail.market_reaction.partial_assets.length ? <div class="workflow-note"><Badge tone="warn">部分覆盖</Badge><span>{detail.market_reaction.partial_assets.map((item) => item.label).join("、")} 已存储但未通过 Eligibility。</span></div> : null}</WorkflowSection>

            <WorkflowSection title="跨资产" eyebrow="CROSS ASSET"><div class="asset-status-grid">{availableAssets.map((item) => <div><strong>{item.label}</strong><Badge tone={reactionTone(item.eligible ? "eligible" : item.status ?? "missing")}>{item.eligible ? "可用于分析" : statusLabel(item.status ?? "missing")}</Badge>{item.is_proxy ? <small>代理：{item.proxy_for}</small> : null}</div>)}</div></WorkflowSection>

            <WorkflowSection title="历史背景" eyebrow="HISTORICAL CONTEXT"><div class="workflow-note"><span>{detail.analysis.run_id ? "历史匹配来自当前 AnalysisRun，并遵守样本下限。" : "尚无 AnalysisRun；不会为填充页面伪造历史百分位。"}</span></div></WorkflowSection>

            <WorkflowSection title="解释" eyebrow="INTERPRETATION"><div class="event-summary-strip"><div><span>分析状态</span><strong>{detail.analysis.status === "completed" ? "已完成" : "尚未运行"}</strong></div><div><span>置信度</span><strong>{detail.analysis.confidence == null ? "—" : `${Math.round(detail.analysis.confidence * 100)}%`}</strong></div><div><span>可复现</span><strong>{detail.analysis.reproducibility === "complete" ? "完整" : "—"}</strong></div></div>{detail.analysis.data_gaps.length ? <ul class="boundary-list">{detail.analysis.data_gaps.map((gap) => <li>{gap}</li>)}</ul> : null}{detail.analysis.run_id ? <button type="button" class="button-primary" onClick={() => { setLabOpen(true); onOpenLab(); }}>打开完整复盘</button> : null}</WorkflowSection>

            <WorkflowSection title="证据与数据边界" eyebrow="EVIDENCE"><div class="workflow-note"><strong>{detail.source ? String(detail.source.title ?? "事件来源") : "来源尚未记录"}</strong><span>{detail.data_quality.length} 条质量记录 · 污染等级 {String(detail.contamination.level ?? "未知")}</span></div><DetailsDisclosure label="高级数据详情"><pre class="json-view">{JSON.stringify({ source: detail.source, provenance: detail.data_provenance, quality: detail.data_quality, contamination: detail.contamination }, null, 2)}</pre></DetailsDisclosure></WorkflowSection>
          </div>}
        </Panel>
      </div>

      {dialog === "consensus" && detail ? <Modal title={`添加市场预期 · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><form class="form-stack" onSubmit={saveConsensus}><label>指标<select required value={indicatorKey} onChange={(event) => setIndicatorKey(event.currentTarget.value)}>{detail.supported_indicators.map((item) => <option value={item.key}>{indicatorLabel(item)} · {item.unit}</option>)}</select></label><label>Consensus<input required type="number" step="any" value={consensusValue} onInput={(event) => setConsensusValue(event.currentTarget.value)} /></label><label>Captured At · {localTimeZoneLabel()}<input required type="datetime-local" value={capturedAt} onInput={(event) => setCapturedAt(event.currentTarget.value)} /><small>保存时转换为 UTC；后端严格验证 Captured At &lt; T0。</small></label><label>来源<input required value={sourceName} onInput={(event) => setSourceName(event.currentTarget.value)} /></label><DetailsDisclosure label="高级信息"><label>来源链接<input type="url" value={sourceUrl} onInput={(event) => setSourceUrl(event.currentTarget.value)} /></label><label>核验说明<textarea value={verificationNotes} onInput={(event) => setVerificationNotes(event.currentTarget.value)} /></label></DetailsDisclosure>{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>取消</button><button type="submit" class="button-primary" disabled={busy}>{busy ? "保存中…" : "保存预期"}</button></div></form></Modal> : null}

      {dialog === "consensus-csv" && detail ? <Modal title={`批量导入 Consensus · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><div class="form-stack"><label>CSV 文件<input type="file" accept=".csv,text/csv" onChange={async (event) => { const file = event.currentTarget.files?.[0]; if (file) { setConsensusCsv(await file.text()); setConsensusPreview(null); } }} /></label><p class="method-note">字段：indicator_key, consensus_value, captured_at, source_name。Captured At 必须包含时区。</p>{consensusPreview ? <><div class="import-summary"><Badge tone="good">{consensusPreview.summary.eligible} 可导入</Badge><Badge tone="warn">{consensusPreview.summary.post_t0} Post-T0</Badge><Badge tone="neutral">{consensusPreview.summary.unknown_indicator} 未知指标</Badge><Badge tone="neutral">{consensusPreview.summary.invalid} 无效</Badge></div><div class="preview-table">{consensusPreview.items.slice(0, 20).map((item) => <div><strong>{item.indicator_label}</strong><span>{item.consensus_value}</span><span>{new Date(item.captured_at).toLocaleString()}</span><Badge tone={item.eligible ? "good" : "warn"}>{statusLabel(item.status)}</Badge></div>)}</div></> : null}{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>取消</button>{!consensusPreview ? <button type="button" class="button-primary" disabled={!consensusCsv || busy} onClick={() => void previewConsensusFile()}>{busy ? "检查中…" : "预览并验证"}</button> : <button type="button" class="button-primary" disabled={!consensusPreview.can_confirm || busy} onClick={() => void confirmConsensusFile()}>{busy ? "导入中…" : `确认导入 ${consensusPreview.summary.eligible} 条`}</button>}</div></div></Modal> : null}

      {dialog === "minutes" && detail ? <Modal title={`分钟行情导入 · ${eventType(detail.event.type)}`} onClose={() => setDialog(null)}><div class="wizard-progress">{["事件", "资产", "文件", "列映射", "时区", "验证", "预览", "导入"].map((label, index) => <span class={minuteStep >= index + 1 ? "active" : ""}><b>{index + 1}</b>{label}</span>)}</div><div class="form-stack"><div class="wizard-context"><span>事件</span><strong>{detail.event.title} · {new Date(detail.event.scheduled_at).toLocaleString()}</strong></div>{minuteStep >= 2 ? <label>资产<select value={minuteAsset} onChange={(event) => { setMinuteAsset(event.currentTarget.value); setMinuteStep(2); setMinutePreview(null); }}>{availableAssets.map((item) => <option value={item.key}>{item.label}{item.is_proxy ? "（代理）" : ""}</option>)}</select></label> : null}{minuteStep >= 2 ? <label>CSV 文件<input type="file" accept=".csv,text/csv" onChange={(event) => void readMinuteFile(event.currentTarget.files?.[0] ?? null)} /></label> : null}{minuteStep >= 3 && minuteCsv ? <><div class="column-mapping"><strong>列映射</strong>{(["timestamp", "open", "high", "low", "close", "volume"] as MappingKey[]).map((key) => <label>{key}<select value={minuteMapping[key]} onChange={(event) => setMinuteMapping({ ...minuteMapping, [key]: event.currentTarget.value })}>{csvHeaders(minuteCsv).map((header) => <option value={header}>{header}</option>)}</select></label>)}</div><label>原始时间所用时区<input value={minuteTimezone} onInput={(event) => setMinuteTimezone(event.currentTarget.value)} /><small>例如 UTC、America/New_York、Asia/Shanghai。带时区的时间戳仍按自身时区解析。</small></label><label>来源链接<input type="url" value={minuteSourceUrl} onInput={(event) => setMinuteSourceUrl(event.currentTarget.value)} /></label><label class="check-row"><input type="checkbox" checked={minuteVerified} onChange={(event) => setMinuteVerified(event.currentTarget.checked)} />我已核验文件来源和资产身份</label></> : null}{minutePreview ? <><div class="eligibility-card"><Badge tone={reactionTone(minutePreview.eligibility.status)}>{statusLabel(minutePreview.eligibility.status)}</Badge><strong>{minutePreview.eligibility.bar_count} bars · T-{minutePreview.eligibility.pre_event_minutes}m 至 T+{minutePreview.eligibility.post_event_minutes}m</strong><span>一分钟频率 {Math.round(minutePreview.eligibility.one_minute_interval_ratio * 100)}% · 缺失 {minutePreview.eligibility.missing_bar_count}</span><ul>{[...minutePreview.eligibility.reasons, ...minutePreview.eligibility.limitations].map((item) => <li>{item}</li>)}</ul></div><div class="preview-table">{minutePreview.preview.slice(0, 8).map((item) => <div><strong>{new Date(item.timestamp).toLocaleString()}</strong><span>O {item.open}</span><span>C {item.close}</span></div>)}</div></> : null}{minuteStep === 8 ? <StateMessage title="分钟数据已存储" detail={minutePreview?.eligibility.eligible ? "该数据已通过 Eligibility，可供下一次 AnalysisRun 使用。" : "数据已保留，但未通过 Eligibility，不会进入 Event Engine。"} /> : null}{formError ? <p class="form-error">{formError}</p> : null}<div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setDialog(null)}>{minuteStep === 8 ? "完成" : "取消"}</button>{minuteCsv && !minutePreview ? <button type="button" class="button-primary" disabled={busy} onClick={() => void previewMinutes()}>{busy ? "验证中…" : "验证并预览"}</button> : null}{minutePreview && minuteStep < 8 ? <button type="button" class="button-primary" disabled={busy} onClick={() => void importMinutes()}>{busy ? "导入中…" : minutePreview.eligibility.eligible ? "确认导入" : "存储但不用于分析"}</button> : null}</div></div></Modal> : null}
    </div>
  );
}
