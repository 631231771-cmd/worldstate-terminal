import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";
import type { DataFreshnessResponse, DataProviderStatus } from "../../types";

interface ControlData {
  providers: DataProviderStatus[];
  freshness: DataFreshnessResponse;
  systems: Array<Record<string, unknown>>;
}

export function DataControlWorkspace() {
  const [data, setData] = useState<ControlData | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const marketFileRef = useRef<HTMLInputElement>(null);

  const reload = async () => {
    const [providers, freshness, systemsPayload] = await Promise.all([
      api.dataProviders(),
      api.dataFreshness(),
      api.macroSystems(),
    ]);
    const systems = Array.isArray(systemsPayload.systems)
      ? (systemsPayload.systems as Array<Record<string, unknown>>)
      : [];
    setData({ providers: providers.items, freshness, systems });
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

  const syncBlsState = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const end = new Date();
      const start = new Date(end);
      start.setFullYear(end.getFullYear() - 5);
      const result = await api.syncBlsCurrentState(
        start.toISOString().slice(0, 10),
        end.toISOString().slice(0, 10),
      );
      setMessage(`BLS 当前观测已同步：${String(result.records_written ?? 0)} 条，非 PIT 状态数据`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "BLS 当前观测同步失败");
    } finally {
      setBusy(false);
    }
  };

  const importMarketCsv = async (event: Event) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    const instrumentKey = window.prompt("请输入市场 instrument_key，例如 gold_gc 或 dollar_dxy", "gold_gc");
    if (!instrumentKey) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.importContextMarketCsv({
        instrument_key: instrumentKey,
        csv_text: await file.text(),
        provider_key: "manual_csv",
        source_name: file.name,
        verified: false,
        interval_seconds: 86400,
      });
      setMessage(`已导入 ${String(result.inserted ?? 0)} 条 observed 日线，已标记为上下文数据`);
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "市场 CSV 导入失败");
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
        <div class="page-heading__actions">
          <input ref={marketFileRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => void importMarketCsv(event)} />
          <button class="button-secondary" disabled={busy} onClick={() => marketFileRef.current?.click()}>导入市场 CSV</button>
          <button class="button-secondary" disabled={busy} onClick={() => void syncBlsState()}>同步 BLS 当前观测</button>
          <button class="button-primary" disabled={busy} onClick={() => void bootstrap()}>{busy ? "同步中…" : "Bootstrap Free Data"}</button>
        </div>
      </section>
      {message ? <div class="data-notice"><strong>{message}</strong><p>Fixture 不会自动替代 observed。</p></div> : null}
      <div class="summary-grid data-summary-grid">
        {Object.entries(summary).map(([status, count]) => <Panel title={status} eyebrow="FRESHNESS" key={status}><div class="big-number">{count}</div><p class="method-note">当前数据模式：{data.freshness.data_mode}</p></Panel>)}
      </div>
      <Panel title="Provider 状态" eyebrow="PUBLIC · CREDENTIAL · BLOCKED">
        <div class="provider-setup-grid">{data.providers.map((item) => <article class="provider-card" key={item.provider_id}><header><div><span>{item.provider_id}</span><h3>{item.display_name}</h3></div><Badge tone={item.healthy === true ? "good" : item.healthy === false ? "bad" : "neutral"}>{item.status}</Badge></header><p>{item.configured ? "已配置或公共端点可用" : "未配置"}</p><small>{item.last_error ?? item.capabilities.join(" · ")}</small></article>)}</div>
      </Panel>
      <Panel title="宏观系统覆盖" eyebrow="OBSERVED COMPONENT COVERAGE">
        <div class="provider-setup-grid">
          {data.systems.map((system) => (
            <article class="provider-card" key={String(system.key)}>
              <header><div><span>{String(system.key)}</span><h3>{String(system.title)}</h3></div><Badge tone={system.status === "available" ? "good" : system.status === "partial" ? "warn" : "bad"}>{String(system.status)}</Badge></header>
              <p>{String(system.available_components ?? 0)} / {String(system.component_count ?? 0)} 个组件有观测</p>
              <small>coverage {String(system.coverage ?? 0)}</small>
            </article>
          ))}
        </div>
      </Panel>
      <Panel title="序列新鲜度" eyebrow="OBSERVED SERIES">
        <div class="freshness-table-wrap"><table class="coverage-table"><thead><tr><th>序列</th><th>Provider</th><th>状态</th><th>最新期间</th><th>可用时间</th></tr></thead><tbody>{data.freshness.items.slice(0, 120).map((item) => <tr key={item.canonical_key}><td><strong>{item.title}</strong><small>{item.canonical_key}</small></td><td>{item.provider}</td><td><Badge tone={item.status === "LIVE" ? "good" : item.status === "MISSING" ? "bad" : "warn"}>{item.status}</Badge></td><td>{item.latest_period ?? "—"}</td><td>{item.available_at ?? "—"}</td></tr>)}</tbody></table></div>
      </Panel>
    </div>
  );
}
