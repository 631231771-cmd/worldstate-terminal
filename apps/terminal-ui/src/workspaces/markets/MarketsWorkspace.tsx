import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

const HORIZONS = ["1d", "1w", "1m", "3m"] as const;

export function MarketsWorkspace() {
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>("1d");
  const [payload, setPayload] = useState<Awaited<ReturnType<typeof api.marketDashboard>> | null>(null);

  useEffect(() => {
    void api.marketDashboard(horizon).then(setPayload).catch(() => setPayload(null));
  }, [horizon]);

  if (!payload) {
    return <StateMessage title="市场数据暂不可用" detail="没有满足当前 data_mode 和交易时段条件的 bars。" />;
  }
  return (
    <div class="workspace">
      <section class="page-heading">
        <div class="eyebrow">MARKETS · CROSS-ASSET CONFIRMATION</div>
        <h1>市场状态</h1>
        <p>把利率、美元、黄金、原油、股票和波动率放在同一张研究表里；这里只展示反应和确认线索，不自动宣称因果。</p>
      </section>
      <div class="toolbar">
        <div class="segmented">
          {HORIZONS.map((item) => <button type="button" class={item === horizon ? "active" : ""} onClick={() => setHorizon(item)} key={item}>{item.toUpperCase()}</button>)}
        </div>
        <Badge tone={payload.data_mode === "observed" ? "good" : "warn"}>{String(payload.data_mode).toUpperCase()}</Badge>
      </div>
      <Panel title="跨资产反应" eyebrow={`WINDOW · ${horizon.toUpperCase()}`} aside={<span class="muted">{String(payload.available_assets ?? 0)} 项可用</span>}>
        <div class="table-wrap">
          <table class="release-table">
            <thead><tr><th>资产</th><th>最新</th><th>变化</th><th>百分位</th><th>来源 / 限制</th></tr></thead>
            <tbody>
              {payload.items.map((item) => {
                const change = item.change_percent as number | null;
                return <tr key={String(item.instrument_key)}>
                  <td><strong>{String(item.title)}</strong><span>{String(item.symbol)} · {String(item.asset_class)}</span></td>
                  <td>{item.latest == null ? "—" : Number(item.latest).toFixed(3)}</td>
                  <td class={change != null && change >= 0 ? "positive" : "negative"}>{change == null ? "—" : `${change.toFixed(2)}%`}</td>
                  <td>{item.percentile == null ? "样本不足" : `${String(item.percentile)}%`}</td>
                  <td><Badge tone={item.is_proxy ? "warn" : "info"}>{item.is_proxy ? "代理资产" : String(item.provider)}</Badge>{item.limitation ? <span>{String(item.limitation)}</span> : null}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="阅读提示" eyebrow="METHOD">
        <ul class="boundary-list"><li>百分位只基于当前保存的 bars，样本不足不会输出伪造概率。</li><li>ZT/ZN 等收益率代理的方向与现金收益率相反，详情中保持原始代理语义。</li><li>缺失的资产不会使用 fixture 补齐。</li></ul>
      </Panel>
    </div>
  );
}

