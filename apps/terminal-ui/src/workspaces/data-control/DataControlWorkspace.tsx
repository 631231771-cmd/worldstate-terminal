import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";
import type { DataFreshnessResponse, DataProviderStatus } from "../../types";

interface ControlData {
  providers: DataProviderStatus[];
  freshness: DataFreshnessResponse;
}

export function DataControlWorkspace() {
  const [data, setData] = useState<ControlData | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = async () => {
    const [providers, freshness] = await Promise.all([api.dataProviders(), api.dataFreshness()]);
    setData({ providers: providers.items, freshness });
  };

  useEffect(() => {
    void reload().catch((error) => setMessage(error instanceof Error ? error.message : "数据控制中心暂不可用"));
  }, []);

  const bootstrap = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.bootstrapFree();
      setMessage(`公共数据同步：${String(result.status ?? "已提交")}`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "公共数据同步失败");
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <StateMessage title="正在读取数据控制中心" detail="检查 Provider、最新观测和数据新鲜度。" />;
  const summary = data.freshness.summary;
  return (
    <div class="workspace data-foundation">
      <section class="page-heading">
        <div><div class="eyebrow">DATA CONTROL CENTER · v0.7</div><h1>数据控制中心</h1><p>观察真实数据是否存在、是否过期，以及哪些 Provider 可以继续同步。</p></div>
        <button class="button-primary" disabled={busy} onClick={() => void bootstrap()}>{busy ? "同步中…" : "Bootstrap Free Data"}</button>
      </section>
      {message ? <div class="data-notice"><strong>{message}</strong><p>Fixture 不会自动替代 observed。</p></div> : null}
      <div class="summary-grid data-summary-grid">
        {Object.entries(summary).map(([status, count]) => <Panel title={status} eyebrow="FRESHNESS" key={status}><div class="big-number">{count}</div><p class="method-note">当前数据模式：{data.freshness.data_mode}</p></Panel>)}
      </div>
      <Panel title="Provider 状态" eyebrow="PUBLIC · CREDENTIAL · BLOCKED">
        <div class="provider-setup-grid">{data.providers.map((item) => <article class="provider-card" key={item.provider_id}><header><div><span>{item.provider_id}</span><h3>{item.display_name}</h3></div><Badge tone={item.healthy === true ? "good" : item.healthy === false ? "bad" : "neutral"}>{item.status}</Badge></header><p>{item.configured ? "已配置或公共端点可用" : "未配置"}</p><small>{item.last_error ?? item.capabilities.join(" · ")}</small></article>)}</div>
      </Panel>
      <Panel title="序列新鲜度" eyebrow="OBSERVED SERIES">
        <div class="freshness-table-wrap"><table class="coverage-table"><thead><tr><th>序列</th><th>Provider</th><th>状态</th><th>最新期间</th><th>可用时间</th></tr></thead><tbody>{data.freshness.items.slice(0, 120).map((item) => <tr key={item.canonical_key}><td><strong>{item.title}</strong><small>{item.canonical_key}</small></td><td>{item.provider}</td><td><Badge tone={item.status === "LIVE" ? "good" : item.status === "MISSING" ? "bad" : "warn"}>{item.status}</Badge></td><td>{item.latest_period ?? "—"}</td><td>{item.available_at ?? "—"}</td></tr>)}</tbody></table></div>
      </Panel>
    </div>
  );
}
