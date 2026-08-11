import { useEffect, useMemo, useState } from "preact/hooks";
import type { ReleaseDetail, ReleaseSummary } from "../../types";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Modal, Panel, StateMessage } from "../../components/Primitives";
import { EventLabWorkspace } from "../event-lab/EventLabWorkspace";
import { fromLocalDateTimeInput, localTimeZoneLabel, toLocalDateTimeInput } from "../../utils/time";

type EventTab = "upcoming" | "recent" | "all";

type IndicatorOption = { key: string; label: string };

const INDICATORS: Record<string, IndicatorOption[]> = {
  US_CPI: [
    { key: "headline_cpi_mom", label: "Headline CPI MoM" },
    { key: "headline_cpi_yoy", label: "Headline CPI YoY" },
    { key: "core_cpi_mom", label: "Core CPI MoM" },
    { key: "core_cpi_yoy", label: "Core CPI YoY" },
  ],
  US_NFP: [
    { key: "nonfarm_payrolls", label: "Nonfarm payrolls" },
    { key: "unemployment_rate", label: "Unemployment rate" },
    { key: "average_hourly_earnings_mom", label: "Average hourly earnings MoM" },
    { key: "average_hourly_earnings_yoy", label: "Average hourly earnings YoY" },
    { key: "labor_force_participation", label: "Labor force participation" },
  ],
  FOMC: [
    { key: "target_rate_upper", label: "Target rate upper bound" },
    { key: "target_rate_lower", label: "Target rate lower bound" },
  ],
};

function eventTone(item: ReleaseSummary): "good" | "warn" | "neutral" | "info" {
  if (item.analysis_status === "completed" && item.reproducibility_status === "complete") return "good";
  if (item.status === "scheduled") return "info";
  return "warn";
}

function eventType(item: ReleaseSummary): string {
  if (item.release_type === "US_CPI") return "CPI";
  if (item.release_type === "US_NFP") return "NFP";
  if (item.release_type === "FOMC") return "FOMC";
  return item.release_type;
}

function localDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function localTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function indicatorOptions(item: ReleaseSummary): IndicatorOption[] {
  return INDICATORS[item.release_type] ?? [{ key: item.release_type.toLowerCase(), label: "Release value" }];
}

export function EventsBoard({
  releases,
  selected,
  detail,
  onSelect,
  onOpenLab,
  onOpenDataSources,
}: {
  releases: ReleaseSummary[];
  selected: ReleaseSummary | null;
  detail: ReleaseDetail | null;
  onSelect: (release: ReleaseSummary) => void;
  onOpenLab: () => void;
  onOpenDataSources: () => void;
}) {
  const [labOpen, setLabOpen] = useState(false);
  const [eventTab, setEventTab] = useState<EventTab>("upcoming");
  const [consensusOpen, setConsensusOpen] = useState(false);
  const [indicatorKey, setIndicatorKey] = useState("");
  const [consensusValue, setConsensusValue] = useState("");
  const [sourceName, setSourceName] = useState("Manual consensus");
  const [sourceUrl, setSourceUrl] = useState("");
  const [capturedAt, setCapturedAt] = useState(toLocalDateTimeInput());
  const [consensusError, setConsensusError] = useState<string | null>(null);
  const [savingConsensus, setSavingConsensus] = useState(false);

  useEffect(() => {
    if (!selected) return;
    if (selected.status === "scheduled" && eventTab === "recent") setEventTab("upcoming");
    if (selected.status === "released" && eventTab === "upcoming") setEventTab("recent");
  }, [eventTab, selected?.id, selected?.status]);

  const visibleReleases = useMemo(() => {
    if (eventTab === "all") return releases.slice(0, 80);
    return releases.filter((item) => eventTab === "recent" ? item.status === "released" : item.status === "scheduled").slice(0, 80);
  }, [eventTab, releases]);

  if (!releases.length) {
    return (
      <StateMessage
        title="暂无宏观事件"
        detail="请先在数据源页面加载官方事件日历。"
        action={<button type="button" class="button-primary" onClick={onOpenDataSources}>打开数据源</button>}
      />
    );
  }

  if (labOpen && selected) {
    return (
      <div class="workspace workspace--product">
        <button type="button" class="button-secondary" onClick={() => setLabOpen(false)}>← 返回事件</button>
        <EventLabWorkspace release={selected} onRefresh={async () => undefined} />
      </div>
    );
  }

  const hasActual = detail ? Object.values(detail.values).some((value) => value.actual != null) : false;
  const hasConsensus = detail ? Object.values(detail.values).some((value) => value.consensus != null) : false;
  const options = selected ? indicatorOptions(selected) : [];

  function openConsensus() {
    setConsensusError(null);
    setIndicatorKey(options[0]?.key ?? "");
    setConsensusValue("");
    setCapturedAt(toLocalDateTimeInput());
    setConsensusOpen(true);
  }

  async function saveConsensus(event: Event) {
    event.preventDefault();
    if (!selected) return;
    setConsensusError(null);
    setSavingConsensus(true);
    try {
      await api.appendConsensus(selected.id, {
        indicator_key: indicatorKey,
        consensus_value: Number(consensusValue),
        source_name: sourceName.trim() || "Manual consensus",
        source_url: sourceUrl.trim() || undefined,
        captured_at: fromLocalDateTimeInput(capturedAt),
        quality_grade: "C",
        is_manual: true,
      });
      setConsensusOpen(false);
      onSelect(selected);
    } catch (error) {
      setConsensusError(error instanceof Error ? error.message : "Consensus 保存失败，请检查时间是否早于发布时间。");
    } finally {
      setSavingConsensus(false);
    }
  }

  return (
    <div class="workspace workspace--product">
      <section class="page-heading page-heading--compact">
        <div>
          <div class="eyebrow">EVENTS / WORKFLOW</div>
          <h1>宏观事件</h1>
          <p>按“发生了什么 → 预期如何 → 市场如何反应 → 历史背景 → 证据”阅读。</p>
        </div>
        <div class="page-heading__aside"><Badge tone="info">{releases.length} 个事件</Badge></div>
      </section>

      <div class="events-layout">
        <Panel title="事件列表" eyebrow="CALENDAR / RELEASES">
          <div class="tabs-bar" role="tablist" aria-label="事件筛选">
            {(["upcoming", "recent", "all"] as EventTab[]).map((tab) => (
              <button type="button" class={eventTab === tab ? "active" : ""} onClick={() => setEventTab(tab)} role="tab" aria-selected={eventTab === tab}>
                {tab === "upcoming" ? "即将发生" : tab === "recent" ? "近期已发布" : "全部"}
              </button>
            ))}
          </div>
          <div class="event-list">
            {visibleReleases.length ? visibleReleases.map((item) => (
              <button
                type="button"
                class={selected?.id === item.id ? "event-list__row event-list__row--active" : "event-list__row"}
                key={item.id}
                onClick={() => { setLabOpen(false); onSelect(item); }}
              >
                <span class="event-list__date">{localDate(item.scheduled_at)}</span>
                <span><strong>{eventType(item)}</strong><small>{localTime(item.scheduled_at)} / {item.period_label}</small></span>
                <Badge tone={eventTone(item)}>{item.status === "scheduled" ? "即将发生" : item.status === "released" ? "已发布" : item.status}</Badge>
              </button>
            )) : <div class="empty-action"><div><h3>此视图暂无事件</h3><p>切换到“全部”查看完整事件日历。</p></div></div>}
          </div>
        </Panel>

        <Panel title={selected ? `${eventType(selected)} / ${selected.period_label}` : "选择一个事件"} eyebrow="EVENT DETAIL">
          {selected ? (
            <div class="event-detail">
              <div class="event-detail__headline"><strong>{eventType(selected)}</strong><span>{new Date(selected.scheduled_at).toLocaleString()}</span><Badge tone={eventTone(selected)}>{selected.status === "scheduled" ? "即将发生" : "已发布"}</Badge></div>
              <div class="board-grid board-grid--markets">
                <div class="metric-tile"><span class="metric-tile__label">实际值</span><strong class="metric-tile__value">{hasActual ? "已记录" : "—"}</strong><span class="metric-tile__meta">{hasActual ? "事件数据可用" : "尚未发布或缺少数据"}</span></div>
                <div class="metric-tile"><span class="metric-tile__label">市场预期</span><strong class="metric-tile__value">{hasConsensus ? "已记录" : "—"}</strong><span class="metric-tile__meta">{hasConsensus ? "发布时间前快照" : "添加发布时间前预期"}</span></div>
                <div class="metric-tile"><span class="metric-tile__label">市场反应</span><strong class="metric-tile__value">{detail?.latest_analysis ? "可分析" : "—"}</strong><span class="metric-tile__meta">{detail?.latest_analysis ? "已有结构化分析" : "需要导入分钟行情"}</span></div>
              </div>
              {!hasConsensus ? (
                <div class="empty-action">
                  <div><h3>尚未记录发布时间前预期</h3><p>在 T0 之前添加 Consensus，才能计算 Surprise。</p></div>
                  <button type="button" class="button-primary" onClick={openConsensus}>添加预期</button>
                </div>
              ) : null}
              <DetailsDisclosure label="高级事件信息"><dl class="detail-grid"><div><dt>状态</dt><dd>{selected.status}</dd></div><div><dt>数据模式</dt><dd>{selected.data_mode}</dd></div><div><dt>干净窗口</dt><dd>{selected.clean_window ? "是" : "否 / 未验证"}</dd></div><div><dt>污染级别</dt><dd>{selected.contamination_level}</dd></div></dl></DetailsDisclosure>
              {selected.analysis_status === "completed" ? <button type="button" class="button-primary" onClick={() => { setLabOpen(true); onOpenLab(); }}>打开事件实验室</button> : null}
            </div>
          ) : <div class="empty-action"><div><h3>选择一个事件开始</h3><p>系统优先选中近期已发布并且有可复现分析的事件。</p></div></div>}
        </Panel>
      </div>

      {consensusOpen && selected ? (
        <Modal title={`添加预期 · ${eventType(selected)}`} onClose={() => setConsensusOpen(false)}>
          <form class="form-stack" onSubmit={saveConsensus}>
            <label>指标<select required value={indicatorKey} onChange={(event) => setIndicatorKey((event.currentTarget as HTMLSelectElement).value)}>{options.map((option) => <option value={option.key} key={option.key}>{option.label}</option>)}</select></label>
            <label>预期值<input required type="number" step="any" value={consensusValue} onInput={(event) => setConsensusValue((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>记录时间（{localTimeZoneLabel()}）<input required type="datetime-local" value={capturedAt} onInput={(event) => setCapturedAt((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>来源<input required value={sourceName} onInput={(event) => setSourceName((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>来源链接<input type="url" value={sourceUrl} onInput={(event) => setSourceUrl((event.currentTarget as HTMLInputElement).value)} placeholder="https://…" /></label>
            {consensusError ? <p class="form-error">{consensusError}</p> : null}
            <div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setConsensusOpen(false)}>取消</button><button type="submit" class="button-primary" disabled={savingConsensus}>{savingConsensus ? "保存中…" : "保存预期"}</button></div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
