import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

export function SeriesWorkspace() {
  const [query, setQuery] = useState("");
  const [series, setSeries] = useState<Array<Record<string, unknown>>>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [transform, setTransform] = useState("raw");
  const [history, setHistory] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => void api.series(query).then(setSeries).catch(() => setSeries([])), 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!selected) { setHistory(null); return; }
    void api.seriesHistory(selected, transform).then(setHistory).catch(() => setHistory(null));
  }, [selected, transform]);

  return <div class="workspace">
    <section class="page-heading"><div class="eyebrow">SERIES EXPLORER · POINT IN TIME</div><h1>宏观序列</h1><p>搜索官方序列，查看原始值、变化率、百分位和 z-score。转换只作用于阅读层，数据库始终保留原始 vintage。</p></section>
    <div class="toolbar"><input class="search-input" value={query} onInput={(event) => setQuery((event.currentTarget as HTMLInputElement).value)} placeholder="搜索 CPI、GDP、DGS10…" /><Badge tone="info">observed 优先</Badge></div>
    <div class="two-column two-column--research">
      <Panel title="序列目录" eyebrow="SEARCH RESULTS">
        <div class="series-list">{series.map((item) => <button type="button" class={selected === item.canonical_key ? "series-row active" : "series-row"} key={String(item.canonical_key)} onClick={() => setSelected(String(item.canonical_key))}><span><strong>{String(item.title)}</strong><small>{String(item.canonical_key)} · {String(item.native_id)}</small></span><span>{item.latest_value == null ? "—" : Number(item.latest_value).toFixed(3)}<small>{String(item.unit)}</small></span></button>)}{!series.length ? <StateMessage title="没有匹配序列" detail="当前模式没有可用的序列记录。" /> : null}</div>
      </Panel>
      <Panel title={history ? String(history.title) : "选择一个序列"} eyebrow="OBSERVATION HISTORY">
        {history ? <><div class="segmented series-transforms">{["raw", "mom", "yoy", "3m_annualized", "percentile", "zscore", "moving_average"].map((item) => <button type="button" class={transform === item ? "active" : ""} onClick={() => setTransform(item)} key={item}>{item}</button>)}</div><div class="series-history">{((history.points as Array<Record<string, unknown>>) ?? []).slice(-18).map((point) => <div class="series-history__row" key={String(point.period)}><time>{String(point.period)}</time><strong>{point.transformed == null ? "—" : Number(point.transformed).toFixed(4)}</strong><small>raw {point.value == null ? "—" : Number(point.value).toFixed(4)}</small></div>)}</div><p class="method-note">来源 {String(history.provider)} · {String(history.data_mode)} · {String(history.unit)}</p></> : <p class="muted">从左侧选择序列开始研究。</p>}
      </Panel>
    </div>
  </div>;
}

