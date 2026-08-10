import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Panel, StateMessage } from "../../components/Primitives";

const HORIZONS = ["1d", "1w", "1m", "3m"] as const;

export function MarketsWorkspace() {
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>("1d");
  const [payload, setPayload] = useState<Awaited<ReturnType<typeof api.marketDashboard>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    setError(null);
    setPayload(null);
    void api.marketDashboard(horizon).then(setPayload).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Market data is unavailable.");
    });
  }, [horizon, retryToken]);

  if (error) return <StateMessage title="Market data unavailable" detail={error} action={<button type="button" class="primary-button" onClick={() => setRetryToken((value) => value + 1)}>Retry</button>} />;
  if (!payload) return <StateMessage title="Market data unavailable" detail="No bars satisfy the current data and session requirements." />;
  return (
    <div class="workspace">
      <section class="page-heading">
        <div><div class="eyebrow">MARKETS · CROSS-ASSET CONTEXT</div><h1>Markets</h1><p>Compare rates, dollar, gold, oil, equities and volatility. The default view answers what changed; source details are one click away.</p></div>
      </section>
      <div class="toolbar">
        <div class="segmented">{HORIZONS.map((item) => <button type="button" class={item === horizon ? "active" : ""} onClick={() => setHorizon(item)} key={item}>{item.toUpperCase()}</button>)}</div>
        <Badge tone={payload.data_mode === "observed" ? "good" : "warn"}>{String(payload.data_mode).toUpperCase()}</Badge>
      </div>
      <Panel title="Cross-asset snapshot" eyebrow={`WINDOW · ${horizon.toUpperCase()}`} aside={<span class="muted">{String(payload.available_assets ?? 0)} assets</span>}>
        <div class="table-wrap"><table class="release-table"><thead><tr><th>Asset</th><th>Latest</th><th>Change</th><th>Percentile</th><th>Context</th></tr></thead><tbody>
          {payload.items.map((item) => {
            const change = item.change_percent as number | null;
            const limitation = item.quality_limitation ?? item.limitation;
            return <tr key={String(item.instrument_key)}>
              <td><strong>{String(item.title)}</strong><span>{String(item.symbol)} · {String(item.asset_class)}</span></td>
              <td>{item.latest == null ? "—" : Number(item.latest).toFixed(3)}</td>
              <td class={change != null && change >= 0 ? "positive" : "negative"}>{change == null ? "—" : `${change.toFixed(2)}%`}</td>
              <td>{item.percentile == null ? "Insufficient sample" : `${String(item.percentile)}%`}</td>
              <td><Badge tone={item.is_proxy ? "warn" : "info"}>{item.is_proxy ? "Proxy asset" : String(item.provider)}</Badge>
                {limitation ? <span>{String(limitation)}</span> : null}
                <DetailsDisclosure label="Data details"><dl class="detail-grid">
                  <div><dt>What</dt><dd>{String(item.title)}</dd></div>
                  <div><dt>Direction</dt><dd>{change == null ? "Unavailable" : change >= 0 ? "Higher" : "Lower"}</dd></div>
                  <div><dt>Freshness</dt><dd>{String(item.freshness ?? item.status ?? "Observed")}</dd></div>
                  <div><dt>Quality</dt><dd>{String(item.quality_grade ?? "Not reported")}</dd></div>
                  <div><dt>Limitation</dt><dd>{String(limitation ?? "None reported")}</dd></div>
                </dl></DetailsDisclosure>
              </td>
            </tr>;
          })}
        </tbody></table></div>
      </Panel>
      <Panel title="How to read this" eyebrow="METHOD"><ul class="boundary-list"><li>Percentiles use only locally stored bars; small samples do not produce invented probabilities.</li><li>Context bars are not minute event-window futures data and cannot prove causal order.</li><li>Missing assets remain missing; fixture rows never fill observed dashboards.</li></ul></Panel>
    </div>
  );
}
