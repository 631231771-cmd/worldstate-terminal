import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";
import type {
  BackfillEstimate,
  BackfillJob,
  BackfillRequest,
  CoverageDimension,
  DataCoverageResponse,
  DataProviderStatus,
  Instrument,
} from "../../types";

interface MethodData {
  instruments: Instrument[];
  quality: Record<string, unknown>;
  providers: Array<Record<string, unknown>>;
  providerStatus: DataProviderStatus[];
  coverage: DataCoverageResponse;
  methodology: Record<string, unknown>;
  regime: Record<string, unknown>;
  warnings: string[];
}

const PROVIDERS = [
  { id: "fred_alfred", name: "FRED / ALFRED", aliases: ["fred", "alfred"] },
  { id: "bls_official", name: "BLS", aliases: ["bls"] },
  { id: "federal_reserve_fomc", name: "Federal Reserve", aliases: ["federal_reserve", "fomc"] },
  { id: "trading_economics_consensus", name: "Trading Economics", aliases: ["trading_economics", "te_consensus"] },
  { id: "databento_market", name: "Databento", aliases: ["databento"] },
] as const;

const EVENT_TYPES = [
  { id: "US_CPI", label: "美国 CPI" },
  { id: "US_NFP", label: "美国非农" },
  { id: "FOMC", label: "FOMC" },
] as const;

const FIXED_ASSETS = ["GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"];
const TERMINAL_JOB_STATES = new Set(["completed", "failed", "cancelled", "canceled", "blocked"]);

async function optional<T>(promise: Promise<T>, fallback: T, label: string) {
  try {
    return { value: await promise, warning: null };
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "接口不可用";
    return { value: fallback, warning: `${label}：${detail}` };
  }
}

function localDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function money(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "USD" }).format(value);
}

function compactNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function bytes(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

function readable(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (!value || typeof value !== "object") return "—";
  const item = value as Record<string, unknown>;
  if (item.statement || item.summary || item.reason) return String(item.statement ?? item.summary ?? item.reason);
  if (item.rule || item.dimension) {
    return [item.rule ?? item.dimension, item.value, item.surprise == null ? null : `surprise ${item.surprise}`]
      .filter((part) => part !== null && part !== undefined && part !== "")
      .join(" · ");
  }
  return JSON.stringify(item);
}

function providerMatch(provider: DataProviderStatus, definition: (typeof PROVIDERS)[number]) {
  const key = `${provider.provider_id} ${provider.display_name}`.toLowerCase();
  return key.includes(definition.id) || definition.aliases.some((alias) => key.includes(alias));
}

function completeProviderList(items: DataProviderStatus[]) {
  const claimed = new Set<DataProviderStatus>();
  const fixed = PROVIDERS.map((definition) => {
    const match = items.find((item) => !claimed.has(item) && providerMatch(item, definition));
    if (match) {
      claimed.add(match);
      return { ...match, display_name: match.display_name || definition.name };
    }
    return {
      provider_id: definition.id,
      display_name: definition.name,
      configured: false,
      healthy: null,
      entitlement: null,
      status: "not_configured",
      last_success_at: null,
      last_error: null,
      quota: null,
      data_range: null,
      quality_grade: null,
      next_planned_snapshot: null,
      capabilities: [],
    } satisfies DataProviderStatus;
  });
  return fixed;
}

function healthTone(item: DataProviderStatus): "good" | "warn" | "bad" | "neutral" {
  if (!item.configured) return "neutral";
  if (item.healthy === true) return "good";
  if (item.healthy === false) return "bad";
  return "warn";
}

function healthLabel(item: DataProviderStatus) {
  if (!item.configured) return "未配置";
  if (item.healthy === true) return "健康";
  if (item.healthy === false) return "异常";
  return item.status || "待检查";
}

function CoverageCell({ value }: { value?: CoverageDimension }) {
  if (!value) {
    return <span class="coverage-empty">未返回</span>;
  }
  const stored = value.stored ?? Boolean(value.data_mode ?? value.mode);
  const eligible = value.analysis_eligible ?? value.available ?? ["analysis_ready", "available", "complete", "observed", "ready", "ok"].includes(value.status);
  const mode = value.data_mode ?? value.mode;
  const quality = value.quality_grade ?? value.quality;
  const storedCount = value.stored_record_count ?? value.record_count ?? 0;
  const eligibleCount = value.analysis_eligible_record_count ?? (eligible ? storedCount : 0);
  return (
    <div class="coverage-cell">
      <Badge tone={eligible ? (mode === "fixture" ? "warn" : "good") : stored ? "warn" : "neutral"}>
        {eligible ? "可用于分析" : stored ? "仅已存储" : "缺失"}
      </Badge>
      <strong>已存 {storedCount} · 合格 {eligibleCount}</strong>
      <small>{!eligible ? value.eligibility_reason ?? value.missing_reason ?? "尚未达到分析条件" : quality ? `${mode ?? "unknown"} · 质量 ${quality}` : "已通过选择条件，但尚无可核验质量等级"}</small>
    </div>
  );
}

export function DataMethodsWorkspace() {
  const [data, setData] = useState<MethodData | null>(null);
  const [startDate, setStartDate] = useState("2015-01-01");
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [eventTypes, setEventTypes] = useState<string[]>(EVENT_TYPES.map((item) => item.id));
  const [estimate, setEstimate] = useState<BackfillEstimate | null>(null);
  const [job, setJob] = useState<BackfillJob | null>(null);
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void Promise.all([
      optional(api.instruments(), [] as Instrument[], "资产注册表不可用"),
      optional(api.dataQuality(), {} as Record<string, unknown>, "质量概览不可用"),
      optional(api.providerRuns(), [] as Array<Record<string, unknown>>, "Provider运行记录不可用"),
      optional(api.dataProviders(), { items: [] }, "Provider Setup接口不可用"),
      optional(api.dataCoverage(), { items: [] }, "Data Coverage接口不可用"),
      optional(api.methodology(), {} as Record<string, unknown>, "方法接口不可用"),
      optional(api.regime(), {} as Record<string, unknown>, "Regime接口不可用"),
    ]).then(([instruments, quality, providerRuns, providerStatus, coverage, methodology, regime]) => {
      if (!alive) return;
      setData({
        instruments: instruments.value,
        quality: quality.value,
        providers: providerRuns.value,
        providerStatus: completeProviderList(providerStatus.value.items ?? []),
        coverage: coverage.value,
        methodology: methodology.value,
        regime: regime.value,
        warnings: [
          instruments.warning,
          quality.warning,
          providerRuns.warning,
          providerStatus.warning,
          coverage.warning,
          methodology.warning,
          regime.warning,
        ].filter((item): item is string => Boolean(item)),
      });
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!job || TERMINAL_JOB_STATES.has(job.status.toLowerCase())) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.backfillJob(job.id);
        if (active) {
          setJob(next);
          setBackfillMessage(null);
        }
      } catch (reason) {
        if (active) {
          setBackfillMessage(reason instanceof Error ? `进度读取失败：${reason.message}` : "进度读取失败。稍后会重试。");
        }
      } finally {
        if (active) timer = window.setTimeout(() => void poll(), 2_500);
      }
    };
    timer = window.setTimeout(() => void poll(), 1_000);
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job?.id, job?.status]);

  const requestPayload = useMemo<BackfillRequest>(
    () => ({ start_date: startDate, end_date: endDate, event_types: eventTypes, assets: FIXED_ASSETS }),
    [startDate, endDate, eventTypes],
  );

  if (!data) {
    return <StateMessage title="正在读取数据基础" detail="汇总 Provider、配额、覆盖范围、质量等级和算法版本。" />;
  }

  const configuredCount = data.providerStatus.filter((item) => item.configured).length;
  const healthyCount = data.providerStatus.filter((item) => item.configured && item.healthy).length;
  const coverageDimensions = data.coverage.items.flatMap((item) => [item.actual, item.consensus, item.intraday, item.daily]);
  const eligibleCoverage = coverageDimensions.filter(
    (item) => item.analysis_eligible ?? item.available ?? ["analysis_ready", "available", "complete", "observed", "ready", "ok"].includes(item.status),
  ).length;
  const storedCoverage = coverageDimensions.filter((item) => item.stored ?? Boolean(item.data_mode ?? item.mode)).length;
  const observedCoverage = coverageDimensions.filter(
    (item) => (item.data_mode ?? item.mode) === "observed" && (item.analysis_eligible ?? item.available),
  ).length;

  const resetEstimate = () => {
    setEstimate(null);
    setBackfillMessage(null);
  };

  const toggleEvent = (eventType: string) => {
    setEventTypes((current) =>
      current.includes(eventType) ? current.filter((item) => item !== eventType) : [...current, eventType],
    );
    resetEstimate();
  };

  const estimateBackfill = async () => {
    if (!eventTypes.length) {
      setBackfillMessage("至少选择一种事件类型后才能估算。");
      return;
    }
    if (!startDate || !endDate || startDate > endDate) {
      setBackfillMessage("请检查回填的起止日期。");
      return;
    }
    setBackfillBusy(true);
    setBackfillMessage(null);
    setEstimate(null);
    try {
      setEstimate(await api.estimateBackfill(requestPayload));
    } catch (reason) {
      setBackfillMessage(
        reason instanceof Error
          ? `成本估算暂不可用：${reason.message}`
          : "成本估算暂不可用；Provider可能尚未配置。",
      );
    } finally {
      setBackfillBusy(false);
    }
  };

  const startBackfill = async () => {
    if (!estimate?.allow_execute) return;
    setBackfillBusy(true);
    setBackfillMessage(null);
    try {
      setJob(await api.startBackfill({ ...requestPayload, estimate_id: estimate.estimate_id }));
    } catch (reason) {
      setBackfillMessage(reason instanceof Error ? `无法启动回填：${reason.message}` : "无法启动回填。请检查预算门和Provider配置。");
    } finally {
      setBackfillBusy(false);
    }
  };

  const cancelBackfill = async () => {
    if (!job) return;
    setBackfillBusy(true);
    try {
      setJob(await api.cancelBackfill(job.id));
      setBackfillMessage("已提交取消请求，已写入的数据会保留并可追溯。");
    } catch (reason) {
      setBackfillMessage(reason instanceof Error ? `取消失败：${reason.message}` : "取消失败。请稍后重试。");
    } finally {
      setBackfillBusy(false);
    }
  };

  const progress = Math.max(0, Math.min(100, job?.progress_percent ?? 0));

  return (
    <div class="workspace data-foundation">
      <section class="page-heading">
        <div>
          <div class="eyebrow">DATA FOUNDATION · v0.7</div>
          <h1>数据与方法</h1>
          <p>先看数据是否真实、完整并在预算内，再谈市场解释。密钥、授权和付费下载都不会在这里暴露或被默认执行。</p>
        </div>
      </section>

      {data.warnings.length ? (
        <div class="data-notice" role="status">
          <strong>部分能力尚未配置</strong>
          <p>页面已降级运行；不影响查看现有研究数据。</p>
          <details><summary>查看接口状态</summary><ul>{data.warnings.map((item) => <li key={item}>{item}</li>)}</ul></details>
        </div>
      ) : null}

      <div class="summary-grid data-summary-grid">
        <Panel title="已配置 Provider" eyebrow="SETUP">
          <div class="big-number">{configuredCount}<small> / {data.providerStatus.length}</small></div>
          <p class="method-note">其中 {healthyCount} 个通过最近一次健康检查</p>
        </Panel>
        <Panel title="分析合格覆盖" eyebrow="STORED ≠ ELIGIBLE">
          <div class="big-number">{eligibleCoverage}<small> / {coverageDimensions.length || "—"}</small></div>
          <p class="method-note">已存 {storedCoverage} 个单元；observed 且合格 {observedCoverage} 个。存在记录不等于可用于分析。</p>
        </Panel>
        <Panel title="回填研究范围" eyebrow="FIXED SCOPE">
          <div class="big-number">3 × 9</div>
          <p class="method-note">CPI / 非农 / FOMC × 固定九类期货资产</p>
        </Panel>
        <Panel title="默认数据模式" eyebrow="DATA MODE">
          <div class="big-number big-number--word">{data.coverage.data_mode ?? "observed"}</div>
          <p class="method-note">正式历史匹配默认排除 fixture</p>
        </Panel>
      </div>

      <Panel title="Provider Setup" eyebrow="CONFIGURATION · HEALTH · ENTITLEMENT">
        <div class="provider-setup-grid">
          {data.providerStatus.map((item) => {
            const quotaLimit = item.quota?.limit ?? null;
            const quotaUsed = item.quota?.used ?? null;
            const quotaRatio = quotaLimit && quotaUsed !== null ? Math.min(100, (quotaUsed / quotaLimit) * 100) : null;
            return (
              <article class="provider-card" key={item.provider_id}>
                <header>
                  <div><span>{item.provider_id}</span><h3>{item.display_name}</h3></div>
                  <Badge tone={healthTone(item)}>{healthLabel(item)}</Badge>
                </header>
                <dl>
                  <div><dt>授权</dt><dd>{item.entitlement ?? (item.configured ? "待确认" : "未配置")}</dd></div>
                  <div><dt>质量</dt><dd>{item.quality_grade ?? "—"}</dd></div>
                  <div><dt>数据范围</dt><dd>{item.data_range?.start && item.data_range?.end ? `${item.data_range.start} → ${item.data_range.end}` : "尚无可用范围"}</dd></div>
                  <div><dt>上次成功</dt><dd>{localDate(item.last_success_at)}</dd></div>
                  <div><dt>下次共识快照</dt><dd>{localDate(item.next_planned_snapshot)}</dd></div>
                </dl>
                <div class="quota-block">
                  <div><span>配额 {item.quota?.period ?? ""}</span><strong>{item.quota ? `${compactNumber(item.quota.used)} / ${compactNumber(item.quota.limit)}` : "未返回"}</strong></div>
                  <div class="quota-bar"><span style={{ width: `${quotaRatio ?? 0}%` }} /></div>
                  <small>{item.quota?.remaining == null ? "剩余额度未知" : `剩余 ${compactNumber(item.quota.remaining)}`}</small>
                </div>
                <div class="capability-list">
                  {item.capabilities.length ? item.capabilities.map((capability) => <span key={capability}>{capability}</span>) : <span>能力声明不可用</span>}
                </div>
                {item.last_error ? <p class="provider-error">最近错误：{item.last_error}</p> : null}
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel title="历史数据回填" eyebrow="ESTIMATE → BUDGET GATE → EXECUTE">
        <div class="backfill-layout">
          <div class="backfill-form">
            <div class="form-grid">
              <label><span>开始日期</span><input type="date" value={startDate} onInput={(event) => { setStartDate(event.currentTarget.value); resetEstimate(); }} /></label>
              <label><span>结束日期</span><input type="date" value={endDate} onInput={(event) => { setEndDate(event.currentTarget.value); resetEstimate(); }} /></label>
            </div>
            <fieldset>
              <legend>事件类型</legend>
              <div class="selection-chips">
                {EVENT_TYPES.map((item) => (
                  <button type="button" class={eventTypes.includes(item.id) ? "active" : ""} onClick={() => toggleEvent(item.id)} key={item.id}>
                    {item.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend>固定资产范围</legend>
              <div class="locked-assets">{FIXED_ASSETS.map((asset) => <span key={asset}>{asset}</span>)}</div>
              <p>DX、VX 均为期货；ZT、ZN 为美债期货价格代理，不是现金收益率。</p>
            </fieldset>
            <div class="button-row">
              <button type="button" class="secondary-button" disabled={backfillBusy} onClick={() => void estimateBackfill()}>
                {backfillBusy && !job ? "正在估算…" : "先估算成本"}
              </button>
              <button type="button" class="primary-button" disabled={backfillBusy || !estimate?.allow_execute} onClick={() => void startBackfill()}>
                执行回填
              </button>
            </div>
            <p class="method-note">系统会跳过已存在的数据。未通过成本估算与预算门时，“执行回填”始终不可用。</p>
          </div>

          <div class={`estimate-card ${estimate?.allow_execute ? "estimate-card--allowed" : ""}`}>
            <div class="eyebrow">COST ESTIMATE</div>
            {estimate ? (
              <>
                <div class="estimate-metrics">
                  <div><span>事件</span><strong>{estimate.event_count}</strong></div>
                  <div><span>资产</span><strong>{estimate.asset_count}</strong></div>
                  <div><span>预计记录</span><strong>{compactNumber(estimate.records_to_download ?? estimate.estimated_records)}</strong></div>
                  <div><span>预计数据量</span><strong>{bytes(estimate.estimated_bytes)}</strong></div>
                </div>
                <div class="cost-gate">
                  <span>预计费用</span><strong>{money(estimate.estimated_cost_usd)}</strong>
                  <p>预算上限 {money(estimate.budget_limit_usd)}</p>
                  <Badge tone={estimate.allow_execute ? "good" : "bad"}>{estimate.allow_execute ? "允许执行" : "预算门已阻止"}</Badge>
                </div>
                <p class="estimate-range">{estimate.start_date} → {estimate.end_date} · {estimate.minute_range ?? `T-${estimate.pre_minutes ?? 90}m → T+${estimate.post_minutes ?? 240}m`}</p>
                {estimate.datasets.length ? <ul class="dataset-list">{estimate.datasets.map((item) => <li key={item.dataset}><strong>{item.dataset}</strong><span>{compactNumber(item.estimated_records)} 条 · {money(item.estimated_cost_usd)}</span></li>)}</ul> : null}
                {estimate.blocked_reason ? <div class="inline-warning">{estimate.blocked_reason}</div> : null}
              </>
            ) : (
              <div class="estimate-placeholder"><strong>尚未估算</strong><p>先选择日期和事件。系统只对固定 9 类资产估价，不会直接开始付费下载。</p></div>
            )}
          </div>
        </div>

        {job ? (
          <div class="backfill-progress">
            <header><div><span>回填任务 {job.id.slice(0, 10)}</span><strong>{job.current_stage ?? job.status}</strong></div><Badge tone={job.status === "completed" ? "good" : job.status === "failed" ? "bad" : "info"}>{job.status}</Badge></header>
            <div class="progress-track"><span style={{ width: `${progress}%` }} /></div>
            <div class="progress-stats">
              <span>{progress.toFixed(0)}%</span>
              <span>事件 {job.events_completed ?? 0} / {job.events_total ?? "—"}</span>
              <span>下载 {compactNumber(job.downloaded_records)}</span>
              <span>失败 {compactNumber(job.failed_records)}</span>
            </div>
            {job.last_error ? <p class="provider-error">{job.last_error}</p> : null}
            {!TERMINAL_JOB_STATES.has(job.status.toLowerCase()) && (job.can_cancel ?? true) ? <button type="button" class="secondary-button" disabled={backfillBusy} onClick={() => void cancelBackfill()}>取消任务</button> : null}
          </div>
        ) : null}
        {backfillMessage ? <div class="inline-warning" role="status">{backfillMessage}</div> : null}
      </Panel>

      <Panel title="Data Coverage" eyebrow="EVENT × ACTUAL × CONSENSUS × MARKET">
        {data.coverage.items.length ? (
          <div class="table-wrap">
            <table class="coverage-table">
              <thead><tr><th>事件</th><th>官方 Actual<br />已存 / 合格</th><th>PIT Consensus<br />已存 / 合格</th><th>分钟行情<br />已存 / 合格</th><th>日线<br />已存 / 合格</th><th>来源质量</th></tr></thead>
              <tbody>
                {data.coverage.items.map((row) => (
                  <tr key={row.event_type}>
                    <td><strong>{row.title ?? EVENT_TYPES.find((item) => item.id === row.event_type)?.label ?? row.event_type}</strong><span>{row.event_type}</span></td>
                    <td><CoverageCell value={row.actual} /></td>
                    <td><CoverageCell value={row.consensus} /></td>
                    <td><CoverageCell value={row.intraday} /></td>
                    <td><CoverageCell value={row.daily} /></td>
                    <td>{typeof row.source_quality === "string" ? <Badge tone={["A", "B"].includes(row.source_quality) ? "good" : "warn"}>{row.source_quality}</Badge> : row.source_quality ? <CoverageCell value={row.source_quality} /> : <Badge tone="neutral">尚未评估</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div class="empty-panel"><strong>覆盖矩阵尚不可用</strong><p>Provider 未配置或 `/v2/data/coverage` 尚未返回数据。现有研究页面仍可使用 fixture 演示。</p></div>
        )}
        <p class="method-note">“已存储”只说明数据库有记录；“可用于分析”还要求初始/PIT Actual、T0 前合格共识，以及有数据、质量 A–C 且通过完整性对账的行情 Manifest。fixture 不进入正式历史统计。</p>
      </Panel>

      <div class="two-column">
        <Panel title="资产定义与代理披露" eyebrow="INSTRUMENT REGISTRY">
          <div class="instrument-list">
            {data.instruments.map((item) => (
              <article key={item.id}>
                <div><strong>{item.title}</strong><p>{item.symbol} · {item.instrument_type} · {item.exchange ?? "无交易所"}</p></div>
                {item.is_proxy ? <Badge tone="warn">代理：{item.proxy_for}</Badge> : <Badge tone="good">原始定义</Badge>}
              </article>
            ))}
          </div>
        </Panel>
        <Panel title="当前 Regime" eyebrow="TRANSPARENT LABELS">
          <div class="regime-labels">
            {((data.regime.labels as string[] | undefined) ?? []).map((label) => <Badge tone="info" key={label}>{label}</Badge>)}
          </div>
          <p class="callout-copy">{String(data.regime.interpretation ?? "没有可用的状态快照。")}</p>
          <ul class="boundary-list">{((data.regime.evidence as unknown[] | undefined) ?? []).map((item, index) => <li key={`${index}-${readable(item)}`}>{readable(item)}</li>)}</ul>
        </Panel>
      </div>

      <Panel title="Provider运行记录" eyebrow="TRACEABLE FALLBACK">
        <div class="table-wrap">
          <table class="release-table">
            <thead><tr><th>Provider</th><th>操作</th><th>状态</th><th>读取</th><th>写入</th><th>质量</th><th>完成时间</th></tr></thead>
            <tbody>
              {data.providers.slice(0, 20).map((run, index) => (
                <tr key={String(run.id ?? index)}>
                  <td><strong>{String(run.provider_key ?? "—")}</strong></td>
                  <td>{String(run.operation ?? "—")}</td>
                  <td><Badge tone={run.status === "completed" ? "good" : run.status === "blocked" ? "warn" : "bad"}>{String(run.status ?? "unknown")}</Badge></td>
                  <td>{String(run.records_read ?? "—")}</td>
                  <td>{String(run.records_written ?? "—")}</td>
                  <td>{String(run.quality_grade ?? "—")}</td>
                  <td>{localDate(run.completed_at ? String(run.completed_at) : null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="方法边界" eyebrow="REPRODUCIBILITY">
        <div class="method-grid">
          <article><span>工作流</span><ol>{((data.methodology.workflow as unknown[] | undefined) ?? []).map((item, index) => <li key={`${index}-${readable(item)}`}>{readable(item)}</li>)}</ol></article>
          <article><span>因果约束</span><p>{String(data.methodology.causality_policy ?? "—")}</p></article>
          <article><span>代理资产</span><p>{String(data.methodology.proxy_policy ?? "—")}</p></article>
          <article><span>Fixture</span><p>{String(data.methodology.fixture_policy ?? "—")}</p></article>
        </div>
      </Panel>
    </div>
  );
}
