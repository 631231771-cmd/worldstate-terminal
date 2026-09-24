import { useEffect, useState } from "preact/hooks";
import { request } from "../api/transport";
import { TimeSeriesChart } from "./TimeSeriesChart";

interface Quote {
  key: string; label: string; symbol: string; kind: string; unit: string;
  price: number | null; change: number | null; change_unit: string;
  quoted_at: string | null; retrieved_at: string | null;
  delay_minutes: number | null; status: string; error: string | null;
  source_url: string; limitation: string;
  points: Array<{ time: string; value: number }>;
}
interface Quotes { as_of: string; refresh_seconds: number; items: Quote[] }

export function QuoteBoard() {
  const [data, setData] = useState<Quotes | null>(null);
  const [selected, select] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [version, refresh] = useState(0);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let active = true, pending = false;
    const load = async () => {
      if (pending || document.hidden) return;
      pending = true; setBusy(true);
      try {
        const result = await request<Quotes>("/v2/product/quotes", undefined, [], 15000);
        if (!Array.isArray(result.items)) throw new Error("Invalid quote response");
        if (active) { setData(result); setError(false); }
      } catch { if (active) setError(true); }
      finally { pending = false; if (active) setBusy(false); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    const visible = () => { if (!document.hidden) void load(); };
    document.addEventListener("visibilitychange", visible);
    return () => { active = false; clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [version]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 10000); return () => clearInterval(timer); }, []);
  const status = (q: Quote) => {
    if (q.price == null) return "暂不可用";
    if (error || q.error || q.status === "stale" || !q.quoted_at || now - Date.parse(q.quoted_at) > ((q.delay_minutes ?? 0) * 60 + 300) * 1000) return "旧报价 / 休市待更新";
    return q.delay_minutes ? `延迟约 ${q.delay_minutes} 分钟` : "最新参考价 · 延迟未承诺";
  };
  const current = data?.items.find(q => q.key === selected);
  return <section class="quote-board" aria-label="最新市场报价">
    <div class="quote-heading"><div><h2>最新报价</h2><span>每分钟自动检查 · 来源时间始终可见</span></div><button type="button" disabled={busy} onClick={() => refresh(v => v + 1)}>{busy ? "读取中…" : "更新报价"}</button></div>
    {error ? <p role="status">报价连接暂时中断{data ? "，保留上次结果" : "，稍后自动重试"}。</p> : null}
    {!data ? <p role="status">正在连接黄金与美债报价源…</p> : <div class="quote-grid">{data.items.map(q => <button type="button" class={selected === q.key ? "quote-tile selected" : "quote-tile"} key={q.key} onClick={() => select(selected === q.key ? null : q.key)}>
      <span>{q.label}</span><strong>{q.price == null ? "—" : q.price.toLocaleString("zh-CN", { maximumFractionDigits: q.kind === "yield_index" ? 3 : 4 })}<small>{q.unit}</small></strong>
      <span>{q.change == null ? "" : `${q.change > 0 ? "+" : ""}${q.change.toFixed(2)} ${q.change_unit} · 较前收盘`}</span>
      <small>{status(q)}</small><time>{q.quoted_at ? new Date(q.quoted_at).toLocaleString("zh-CN") : "尚无报价"}</time>
    </button>)}</div>}
    {current ? <div class="quote-detail"><div class="quote-heading"><h3>{current.label} · {current.symbol}</h3><button type="button" onClick={() => select(null)}>收起</button></div>
      {current.points.length > 1 ? <TimeSeriesChart points={current.points} horizon="1w" intraday /> : <p>等待更多报价后显示走势；不补画过去价格。</p>}
      <p>{current.limitation} <a href={current.source_url} target="_blank" rel="noreferrer">查看来源 ↗</a></p>
      <small>此处报价用于盯盘，不作为 CPI/FOMC 分钟事件研究输入。2Y/10Y 期货是价格，不是收益率。</small>
    </div> : null}
  </section>;
}
