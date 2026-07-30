import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";
import type { Instrument } from "../../types";

interface MethodData {
  instruments: Instrument[];
  quality: Record<string, unknown>;
  providers: Array<Record<string, unknown>>;
  methodology: Record<string, unknown>;
  regime: Record<string, unknown>;
}

export function DataMethodsWorkspace() {
  const [data, setData] = useState<MethodData | null>(null);

  useEffect(() => {
    void Promise.all([
      api.instruments(),
      api.dataQuality(),
      api.providerRuns(),
      api.methodology(),
      api.regime(),
    ]).then(([instruments, quality, providers, methodology, regime]) =>
      setData({ instruments, quality, providers, methodology, regime }),
    );
  }, []);

  if (!data) {
    return <StateMessage title="正在读取数据血缘" detail="汇总 Provider、质量等级、代理资产和算法版本。" />;
  }
  const qualityEntries = Object.entries(data.quality).filter(
    ([, value]) => typeof value === "number" || typeof value === "string",
  );

  return (
    <div class="workspace">
      <section class="page-heading">
        <div>
          <div class="eyebrow">DATA PROVENANCE & METHODOLOGY</div>
          <h1>数据与方法</h1>
          <p>不是设置杂物间：这里解释每个结论从哪里来、哪里降级、哪里不能相信。</p>
        </div>
      </section>
      <div class="summary-grid">
        {qualityEntries.slice(0, 4).map(([key, value]) => (
          <Panel title={key.replaceAll("_", " ")} eyebrow="QUALITY" key={key}>
            <div class="big-number">{String(value)}</div>
          </Panel>
        ))}
      </div>
      <div class="two-column">
        <Panel title="资产定义与代理披露" eyebrow="INSTRUMENT REGISTRY">
          <div class="instrument-list">
            {data.instruments.map((item) => (
              <article key={item.id}>
                <div><strong>{item.title}</strong><p>{item.symbol} · {item.instrument_type} · {item.exchange ?? "无交易所"}</p></div>
                {item.is_proxy ? (
                  <Badge tone="warn">代理：{item.proxy_for}</Badge>
                ) : (
                  <Badge tone="good">原始定义</Badge>
                )}
              </article>
            ))}
          </div>
        </Panel>
        <Panel title="当前 Regime" eyebrow="TRANSPARENT LABELS">
          <div class="regime-labels">
            {((data.regime.labels as string[] | undefined) ?? []).map((label) => (
              <Badge tone="info" key={label}>{label}</Badge>
            ))}
          </div>
          <p class="callout-copy">{String(data.regime.interpretation ?? "没有可用的状态快照。")}</p>
          <ul class="boundary-list">
            {((data.regime.evidence as string[] | undefined) ?? []).map((item) => <li key={item}>{item}</li>)}
          </ul>
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
                  <td><Badge tone={run.status === "completed" ? "good" : "bad"}>{String(run.status)}</Badge></td>
                  <td>{String(run.records_read ?? "—")}</td>
                  <td>{String(run.records_written ?? "—")}</td>
                  <td>{String(run.quality_grade ?? "—")}</td>
                  <td>{run.completed_at ? new Date(String(run.completed_at)).toLocaleString("zh-CN") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="方法边界" eyebrow="REPRODUCIBILITY">
        <div class="method-grid">
          <article><span>工作流</span><ol>{((data.methodology.workflow as string[] | undefined) ?? []).map((item) => <li key={item}>{item}</li>)}</ol></article>
          <article><span>因果约束</span><p>{String(data.methodology.causality_policy ?? "—")}</p></article>
          <article><span>代理资产</span><p>{String(data.methodology.proxy_policy ?? "—")}</p></article>
          <article><span>Fixture</span><p>{String(data.methodology.fixture_policy ?? "—")}</p></article>
        </div>
      </Panel>
    </div>
  );
}
