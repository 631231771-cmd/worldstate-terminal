import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../../api/client";
import { CrossAssetChart } from "../../components/CrossAssetChart";
import { Badge, Meter, Panel, StateMessage } from "../../components/Primitives";
import type {
  ContractProvenance,
  ExplanationsResponse,
  HistoricalResponse,
  MarketDatasetProvenance,
  ProvenanceSource,
  ReleaseDetail,
  ReleaseSummary,
  ResearchClaim,
  TimelineResponse,
  WindowsResponse,
} from "../../types";

interface LabData {
  detail: ReleaseDetail;
  windows: WindowsResponse;
  timeline: TimelineResponse;
  historical: HistoricalResponse;
  explanations: ExplanationsResponse;
  claims: ResearchClaim[];
}

const WINDOW_ORDER = ["post_1m", "post_5m", "post_15m", "post_30m", "post_60m", "post_4h"];

function number(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function factText(fact: Record<string, unknown> | string) {
  if (typeof fact === "string") return fact;
  return String(fact.statement ?? fact.summary ?? fact.fact ?? JSON.stringify(fact));
}

function evidenceText(value: Record<string, unknown> | string) {
  if (typeof value === "string") return value;
  return String(
    value.statement ??
      value.summary ??
      value.falsifier ??
      value.unknown ??
      JSON.stringify(value),
  );
}

function instrumentPresentation(key: string, symbol: string, fallbackTitle: string) {
  const normalizedKey = key.toLowerCase();
  const normalizedSymbol = symbol.toUpperCase();
  if (normalizedKey === "zt" || normalizedKey.endsWith("_zt") || /^ZT(?:$|[^A-Z]|[FGHJKMNQUVXZ]\d)/.test(normalizedSymbol)) {
    return {
      title: "2年期美债期货价格",
      note: "ZT · 现金收益率代理",
      isProxy: true,
    };
  }
  if (normalizedKey === "zn" || normalizedKey.endsWith("_zn") || /^ZN(?:$|[^A-Z]|[FGHJKMNQUVXZ]\d)/.test(normalizedSymbol)) {
    return {
      title: "10年期美债期货价格",
      note: "ZN · 现金收益率代理",
      isProxy: true,
    };
  }
  if (normalizedKey === "dx" || normalizedKey.endsWith("_dx") || /^DX(?!Y)(?:$|[^A-Z]|[FGHJKMNQUVXZ]\d)/.test(normalizedSymbol)) {
    return {
      title: "美元指数期货",
      note: "DX · ICE Futures US，非现货 DXY",
      isProxy: false,
    };
  }
  if (normalizedKey === "vx" || normalizedKey.endsWith("_vx") || /^VX(?:$|[^A-Z]|[FGHJKMNQUVXZ]\d)/.test(normalizedSymbol)) {
    return {
      title: "波动率期货",
      note: "VX · CFE，代表波动率预期而非现货 VIX",
      isProxy: false,
    };
  }
  return { title: fallbackTitle, note: symbol, isProxy: false };
}

function sourceTitle(source: ProvenanceSource | string | null | undefined, fallback = "未返回") {
  if (!source) return fallback;
  if (typeof source === "string") return source;
  return source.display_name ?? source.source_name ?? source.provider_key ?? fallback;
}

function sourceMeta(source: ProvenanceSource | string | null | undefined) {
  if (!source || typeof source === "string") return null;
  return source.snapshot_id ?? source.artifact_id ?? source.content_hash?.slice(0, 12) ?? null;
}

function datasetTitle(dataset: MarketDatasetProvenance | string | null | undefined) {
  if (!dataset) return "数据集未返回";
  if (typeof dataset === "string") return dataset;
  return [dataset.provider_key, dataset.dataset, dataset.schema].filter(Boolean).join(" · ") || "数据集未返回";
}

function reconciliationText(
  status: string | null | undefined,
  expected = 0,
  covered = 0,
) {
  if (status === "complete" || status === "matched") return `完整对账 ${covered} / ${expected}`;
  if (status === "partial") return `仅部分对账 ${covered} / ${expected}，不能视为完整`;
  if (status === "attention_required") return `已对账 ${covered} / ${expected}，但存在差异或未解决检查`;
  if (status === "not_applicable") return "当前发布没有需要执行的对账对象";
  if (status === "not_run") return `尚未对账 0 / ${expected}`;
  return "对账状态未返回";
}

export function EventLabWorkspace({
  release,
  onRefresh,
}: {
  release: ReleaseSummary | null;
  onRefresh: () => Promise<void>;
}) {
  const [data, setData] = useState<LabData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string>("");
  const [assistantQuestion, setAssistantQuestion] = useState("请解释这场事件的跨资产传导链与主要不确定性。");
  const [assistantAnswer, setAssistantAnswer] = useState<string | null>(null);
  const [assistantBusy, setAssistantBusy] = useState(false);

  useEffect(() => {
    if (!release) return;
    setLoading(true);
    setError(null);
    setData(null);
    setAssistantAnswer(null);
    api.release(release.id)
      .then((detail) =>
        Promise.all([
          Promise.resolve(detail),
          api.windows(release.id),
          api.timeline(release.id),
          api.historical(release.id),
          api.explanations(release.id),
          detail.latest_analysis
            ? api.claims(detail.latest_analysis.id)
            : Promise.resolve({ run_id: "", items: [] }),
        ]),
      )
      .then(([detail, windows, timeline, historical, explanations, claims]) => {
        setData({ detail, windows, timeline, historical, explanations, claims: claims.items });
        setStage(detail.stages[0]?.key ?? "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "事件研究读取失败。"))
      .finally(() => setLoading(false));
  }, [release?.id]);

  const selectedWindows = useMemo(
    () => data?.windows.items.filter((item) => item.stage_key === stage) ?? [],
    [data, stage],
  );
  const windowMap = useMemo(
    () =>
      new Map(
        selectedWindows.map((item) => [`${item.instrument_key}:${item.window_key}`, item] as const),
      ),
    [selectedWindows],
  );
  const instruments = useMemo(
    () =>
      Array.from(
        new Map(
          selectedWindows.map((item) => {
            const presentation = instrumentPresentation(item.instrument_key, item.symbol, item.instrument_title);
            return [
              item.instrument_key,
              {
                key: item.instrument_key,
                title: presentation.title,
                symbol: item.symbol,
                note: presentation.note,
                isProxy: presentation.isProxy || item.is_proxy,
              },
            ] as const;
          }),
        ).values(),
      ),
    [selectedWindows],
  );
  const presentationTimeline = useMemo(() => {
    if (!data) return null;
    return {
      ...data.timeline,
      series: Object.fromEntries(
        Object.entries(data.timeline.series).map(([key, series]) => {
          const presentation = instrumentPresentation(key, series.symbol, series.title);
          return [
            key,
            {
              ...series,
              title: presentation.title,
              is_proxy: presentation.isProxy || series.is_proxy,
              proxy_for: presentation.isProxy ? presentation.note : series.proxy_for,
            },
          ];
        }),
      ),
    } satisfies TimelineResponse;
  }, [data]);

  if (!release) {
    return <StateMessage title="还没有可研究的事件" detail="先导入或建立一场宏观发布。" />;
  }
  if (loading || !data) {
    return (
      <StateMessage
        title={error ? "事件研究读取失败" : "正在重建事件链"}
        detail={error ?? "组合发布值、阶段窗口、历史样本和候选解释。"}
      />
    );
  }

  const { detail, timeline, historical, explanations, claims } = data;
  const confidence = detail.latest_analysis?.confidence ?? explanations.confidence ?? 0;
  const runId = detail.latest_analysis?.id ?? "—";
  const provenance = detail.data_provenance;
  const dataMode = provenance?.data_mode ?? detail.data_mode ?? (detail.source?.is_fixture ? "fixture" : "unknown");
  const consensusSources = Array.from(
    new Set(Object.values(detail.values).map((item) => item.consensus_source).filter((item): item is string => Boolean(item))),
  );
  const consensusCapturedAt =
    provenance?.consensus_captured_at ??
    Object.values(detail.values).map((item) => item.consensus_captured_at).filter((item): item is string => Boolean(item)).sort().at(-1) ??
    null;
  const officialSource = provenance?.official_source ?? detail.source?.provider_key ?? null;
  const consensusSource = provenance?.consensus_source ?? (consensusSources.join(" / ") || null);
  const marketContracts: ContractProvenance[] = provenance?.contracts?.length
    ? provenance.contracts
    : Array.from(
        new Map(
          data.windows.items.map((item) => [
            item.instrument_key,
            {
              instrument_key: item.instrument_key,
              instrument_title: item.instrument_title,
              symbol: item.symbol,
              contract_code: item.contract_code ?? null,
              dataset: item.dataset ?? null,
            },
          ]),
        ).values(),
      );
  const provenanceGaps = Array.from(
    new Set([...(provenance?.data_gaps ?? []), ...(detail.latest_analysis?.data_gaps ?? [])]),
  );
  const reconciliationSummary = provenance?.reconciliation_summary;
  const reconciliationCopy = reconciliationText(
    provenance?.reconciliation_status,
    reconciliationSummary?.expected_subject_count ?? 0,
    reconciliationSummary?.covered_subject_count ?? 0,
  );

  const askAssistant = async () => {
    setAssistantBusy(true);
    try {
      const result = await api.assistant(detail.id, assistantQuestion);
      setAssistantAnswer(result.answer);
    } catch (reason) {
      setAssistantAnswer(reason instanceof Error ? reason.message : "研究助手暂时不可用。");
    } finally {
      setAssistantBusy(false);
    }
  };

  return (
    <div class="workspace">
      <section class="event-hero">
        <div>
          <div class="event-hero__meta">
            <Badge tone="info">{detail.release_type}</Badge>
            <span>{detail.period_label}</span>
            <span>{new Date(detail.released_at ?? detail.scheduled_at).toLocaleString("zh-CN")}</span>
          </div>
          <h1>{detail.title}</h1>
          <p class="event-hero__classification">{detail.bundle.classification}</p>
          <div class="badge-row">
            <Badge tone={dataMode === "observed" ? "good" : dataMode === "fixture" ? "warn" : "neutral"}>
              DATA MODE · {dataMode.toUpperCase()}
            </Badge>
            {dataMode === "fixture" ? <Badge tone="warn">FIXTURE 演示数据</Badge> : null}
            <Badge tone={detail.contamination.clean_window ? "good" : "bad"}>
              {detail.contamination.clean_window ? "清洁事件窗口" : "窗口受到污染"}
            </Badge>
            <Badge tone="neutral">分析运行 {runId.slice(0, 8)}</Badge>
          </div>
        </div>
        <div class="confidence-card">
          <span>解释置信度</span>
          <strong>{Math.round(confidence * 100)}%</strong>
          <Meter value={confidence} />
          <p>综合数据质量、事件污染、跨资产确认和历史样本。</p>
        </div>
      </section>

      <Panel
        title="发布值与预期差"
        eyebrow="ACTUAL / CONSENSUS / PREVIOUS / REVISION"
        aside={
          <div class="composite-score">
            <span>综合惊喜</span>
            <strong>{number(detail.bundle.score)}</strong>
          </div>
        }
      >
        <div class="value-grid">
          {Object.entries(detail.values).map(([key, value]) => (
            <article class="value-card" key={key}>
              <header>
                <span>{value.name}</span>
                <Badge
                  tone={
                    value.surprise?.direction === "hot"
                      ? "bad"
                      : value.surprise?.direction === "cold"
                        ? "good"
                        : "neutral"
                  }
                >
                  {value.surprise?.direction ?? "未计算"}
                </Badge>
              </header>
              <div class="value-card__primary">
                <strong>{number(value.actual)}</strong><small>{value.unit}</small>
              </div>
              <dl>
                <div><dt>市场共识</dt><dd>{number(value.consensus)}</dd></div>
                <div><dt>前值</dt><dd>{number(value.previous)}</dd></div>
                <div><dt>修正前值</dt><dd>{number(value.revised_previous)}</dd></div>
                <div><dt>原始惊喜</dt><dd>{number(value.surprise?.raw_surprise)}</dd></div>
                <div><dt>阈值缩放</dt><dd>{number(value.surprise?.threshold_scaled_surprise)}</dd></div>
                <div><dt>Z-score</dt><dd>{value.surprise?.surprise_z == null ? "历史样本不足，未计算 Z-score" : number(value.surprise.surprise_z)}</dd></div>
                <div><dt>历史样本</dt><dd>{value.surprise?.history_sample_count ?? "—"}</dd></div>
              </dl>
              <p>共识：{value.consensus_source ?? "来源缺失"} · {value.consensus_captured_at ? new Date(value.consensus_captured_at).toLocaleString("zh-CN") : "快照时间缺失"}</p>
            </article>
          ))}
        </div>
        <div class="reason-strip">
          {detail.bundle.reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
      </Panel>

      <Panel title="数据血缘与合约快照" eyebrow="OFFICIAL → PIT CONSENSUS → MARKET DATA">
        <div class="lineage-grid">
          <article>
            <span>官方 Actual / Revision</span>
            <strong>{sourceTitle(officialSource, "官方来源未返回")}</strong>
            <p>{sourceMeta(officialSource) ? `快照 ${sourceMeta(officialSource)}` : detail.source?.content_hash ? `Artifact ${detail.source.content_hash.slice(0, 12)}` : "尚无SourceArtifact快照信息"}</p>
          </article>
          <article>
            <span>事件前 PIT Consensus</span>
            <strong>{sourceTitle(consensusSource, "共识来源未配置")}</strong>
            <p>{consensusCapturedAt ? new Date(consensusCapturedAt).toLocaleString("zh-CN") : "合格快照时间缺失"}{sourceMeta(consensusSource) ? ` · 快照 ${sourceMeta(consensusSource)}` : ""}</p>
          </article>
          <article>
            <span>市场数据集</span>
            <strong>{datasetTitle(provenance?.market_dataset)}</strong>
            <p>{typeof provenance?.market_dataset === "object" && provenance.market_dataset?.manifest_hash ? `Manifest ${provenance.market_dataset.manifest_hash.slice(0, 12)}` : "逐合约信息见下表"}</p>
          </article>
          <article>
            <span>模式 / 对账</span>
            <strong>{dataMode}</strong>
            <p>{reconciliationCopy}</p>
          </article>
        </div>

        {marketContracts.length ? (
          <div class="table-wrap contract-table-wrap">
            <table class="contract-table">
              <thead><tr><th>资产定义</th><th>实际合约</th><th>Provider Symbol</th><th>Dataset</th><th>到期 / Roll</th></tr></thead>
              <tbody>
                {marketContracts.map((contract) => {
                  const presentation = instrumentPresentation(contract.instrument_key, contract.symbol ?? "", contract.instrument_title ?? contract.instrument_key);
                  return (
                    <tr key={`${contract.instrument_key}:${contract.contract_code ?? "none"}`}>
                      <td><strong>{presentation.title}</strong><span>{presentation.note}</span></td>
                      <td><strong>{contract.contract_code ?? "合约未返回"}</strong><span>{contract.selection_rule ?? "选择规则未返回"}</span></td>
                      <td>{contract.provider_symbol ?? "—"}</td>
                      <td>{contract.dataset ?? (typeof provenance?.market_dataset === "object" ? provenance.market_dataset?.dataset : provenance?.market_dataset) ?? "—"}</td>
                      <td>{contract.expiry ?? contract.last_trade ?? "—"}<span>{contract.roll_status ?? "roll状态未返回"}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div class="empty-panel"><strong>合约快照尚未返回</strong><p>当前分析仍可查看，但不能据此确认具体合约或roll状态。</p></div>
        )}

        <div class="semantic-disclosure">
          <p><strong>DX / VX：</strong>均为期货。DX代表美元指数期货，VX代表波动率预期，不是现货DXY或现货VIX。</p>
          <p><strong>ZT / ZN：</strong>显示美债期货价格变化，只作为现金收益率的代理；这里不输出伪精确的收益率bp变化。</p>
        </div>
        {provenanceGaps.length ? <div class="data-gap-strip"><strong>数据缺口</strong>{provenanceGaps.map((gap) => <span key={gap}>{gap}</span>)}</div> : null}
      </Panel>

      <div class="two-column">
        <Panel title="分析运行可复现性" eyebrow="ANALYSIS RUN">
          <div class="historical-summary">
            <div><span>状态</span><strong>{detail.latest_analysis?.reproducibility_status ?? "legacy"}</strong></div>
            <div><span>Input</span><strong>{detail.latest_analysis?.input_snapshot_hash?.slice(0, 12) ?? "—"}</strong></div>
            <div><span>Config</span><strong>{detail.latest_analysis?.config_hash?.slice(0, 12) ?? "—"}</strong></div>
            <div><span>Output</span><strong>{detail.latest_analysis?.output_hash?.slice(0, 12) ?? "—"}</strong></div>
          </div>
          <p class="method-note">完整哈希、输入清单、算法版本和历史样本清单保存在本次 AnalysisRun 中。</p>
        </Panel>
        <Panel title="结构化研究声明" eyebrow="CLAIMS → EVIDENCE">
          <div class="quality-list">
            {claims.slice(0, 8).map((claim) => (
              <article key={claim.claim_id}>
                <Badge tone={claim.is_inference ? "warn" : "good"}>
                  {claim.is_inference ? "推断" : "事实"}
                </Badge>
                <div><strong>{claim.statement}</strong><p>{claim.evidence_ids.length} 条证据绑定</p></div>
              </article>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="分阶段跨资产反应" eyebrow="RELEASE STAGES">
        <div class="stage-selector">
          {detail.stages.map((item) => (
            <button
              type="button"
              class={stage === item.key ? "active" : ""}
              onClick={() => setStage(item.key)}
              key={item.id}
            >
              <span>T{item.sequence}</span>
              <strong>{item.title}</strong>
              <small>{new Date(item.released_at ?? item.scheduled_at).toLocaleTimeString("zh-CN")}</small>
            </button>
          ))}
        </div>
        <CrossAssetChart timeline={presentationTimeline ?? timeline} />
      </Panel>

      <Panel title="多窗口反应矩阵" eyebrow="EVENT WINDOWS">
        <div class="table-wrap">
          <table class="matrix-table">
            <thead>
              <tr>
                <th>资产</th>
                {WINDOW_ORDER.map((key) => (
                  <th key={key}>{windowMap.get(`${instruments[0]?.key}:${key}`)?.window_label ?? key}</th>
                ))}
                <th>覆盖</th>
              </tr>
            </thead>
            <tbody>
              {instruments.map((instrument) => (
                <tr key={instrument.key}>
                  <td>
                    <strong>{instrument.title}</strong>
                    <span>{instrument.note} {instrument.isProxy ? "· 代理" : ""}</span>
                  </td>
                  {WINDOW_ORDER.map((key) => {
                    const item = windowMap.get(`${instrument.key}:${key}`);
                    const value = item?.return_percent;
                    return (
                      <td
                        key={key}
                        class={value === null || value === undefined ? "" : value > 0 ? "positive" : "negative"}
                      >
                        {number(value)}%
                        {item?.direction_reversal ? <b title="阶段间方向反转">↺</b> : null}
                        {item?.spike_fade ? <b title="冲高回落">↘</b> : null}
                      </td>
                    );
                  })}
                  <td>{Math.round((selectedWindows.find((item) => item.instrument_key === instrument.key)?.coverage_ratio ?? 0) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p class="method-note">
          方向与反转按当前阶段 T0 计算。交易日历为{" "}
          {Array.from(
            new Set(selectedWindows.map((item) => item.calendar_name ?? "unknown")),
          ).join(" / ")}
          ；长窗口属于 exchange-session-lite 实验方法，不代表完整交易所日历。
        </p>
      </Panel>

      <div class="two-column two-column--research">
        <Panel title="确定性事实" eyebrow="COMPUTED FACTS">
          <ul class="fact-list">
            {explanations.facts.map((fact, index) => (
              <li key={`${index}-${factText(fact)}`}><span>{String(index + 1).padStart(2, "0")}</span>{factText(fact)}</li>
            ))}
          </ul>
        </Panel>
        <Panel title="历史样本" eyebrow="FIXED-RECIPE MATCHING">
          <div class="historical-summary">
            <div><span>模式</span><strong>{historical.mode}</strong></div>
            <div><span>过滤前</span><strong>{historical.pre_filter_count}</strong></div>
            <div><span>过滤后</span><strong>{historical.post_filter_count}</strong></div>
            <div><span>可靠性</span><strong>{historical.reliability}</strong></div>
          </div>
          {historical.warning ? <div class="inline-warning">{historical.warning}</div> : null}
          <ol class="filter-chain">
            {historical.filters.map((item) => (
              <li key={item.condition}>
                <span>{item.before} → {item.after}</span>
                <p>{item.condition}</p>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

      <Panel title="候选传导解释" eyebrow="ATTRIBUTION HYPOTHESES">
        <div class="hypothesis-grid">
          {explanations.explanations.map((item, index) => (
            <article class={index === 0 ? "hypothesis hypothesis--primary" : "hypothesis"} key={item.rule_key}>
              <header>
                <div>
                  <span>{index === 0 ? "主候选" : "竞争解释"} · {item.kind}</span>
                  <h3>{item.title}</h3>
                </div>
                <strong>{Math.round(item.confidence * 100)}%</strong>
              </header>
              <p>{item.summary}</p>
              <ol>
                {item.mechanism_steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
              <div class="evidence-columns">
                <div>
                  <span>支持</span>
                  {item.confirming_evidence.map((line) => (
                    <p key={evidenceText(line)}>+ {evidenceText(line)}</p>
                  ))}
                </div>
                <div>
                  <span>反对 / Falsifier</span>
                  {[...item.contradicting_evidence, ...item.unresolved].map((line) => (
                    <p key={evidenceText(line)}>− {evidenceText(line)}</p>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
      </Panel>

      <div class="two-column">
        <Panel title="数据质量与来源" eyebrow="PROVENANCE">
          <div class="quality-list">
            {detail.data_quality.slice(0, 10).map((item, index) => (
              <article key={item.id ?? `${item.source_name}-${index}`}>
                <Badge tone={item.quality_grade === "A" || item.quality_grade === "B" ? "good" : "warn"}>
                  {item.quality_grade}
                </Badge>
                <div><strong>{item.source_name}</strong><p>{item.verification_notes ?? item.source_type}</p></div>
                <div class="badge-row">
                  {item.is_fixture ? <Badge tone="warn">FIXTURE</Badge> : null}
                  {item.is_proxy ? <Badge tone="warn">代理</Badge> : null}
                  {item.is_manual ? <Badge tone="info">手工</Badge> : null}
                </div>
              </article>
            ))}
          </div>
          {detail.source ? (
            <a class="source-link" href={detail.source.url} target="_blank" rel="noreferrer">
              查看来源：{detail.source.title} ↗
            </a>
          ) : null}
        </Panel>
        <Panel title="污染与未知项" eyebrow="LIMITATIONS">
          <div class="contamination-card">
            <strong>{detail.contamination.level.toUpperCase()}</strong>
            <p>{detail.contamination.clean_window ? "没有登记明显重叠事件。" : "分析窗口可能受到其他信息干扰。"}</p>
          </div>
          <ul class="boundary-list">
            {[...detail.contamination.confounding_notes, ...explanations.data_gaps].map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel title="AI 研究侧栏" eyebrow="EVIDENCEPACK ONLY">
        <div class="assistant">
          <div>
            <textarea
              value={assistantQuestion}
              onInput={(event) => setAssistantQuestion((event.currentTarget as HTMLTextAreaElement).value)}
              aria-label="向研究助手提问"
            />
            <button type="button" class="primary-button" disabled={assistantBusy} onClick={() => void askAssistant()}>
              {assistantBusy ? "正在核对证据…" : "生成有证据约束的解释"}
            </button>
            <p class="method-note">未配置 AI 时仍会生成完整模板报告；AI 不能修改确定性计算。</p>
          </div>
          <article class="assistant__answer">
            <div class="eyebrow">RESEARCH REPORT</div>
            <pre>{assistantAnswer ?? explanations.report}</pre>
          </article>
        </div>
      </Panel>
    </div>
  );
}
