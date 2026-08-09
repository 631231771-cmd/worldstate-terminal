import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

export function WorldStateWorkspace() {
  const [state, setState] = useState<Awaited<ReturnType<typeof api.worldState>> | null>(null);
  useEffect(() => { void api.worldState().then(setState).catch(() => setState(null)); }, []);
  if (!state) return <StateMessage title="宏观状态暂不可用" detail="当前 observed 数据模式没有足够的点时序列。" />;
  return <div class="workspace">
    <section class="page-heading"><div class="eyebrow">WORLD STATE · DETERMINISTIC SNAPSHOT</div><h1>美国宏观状态</h1><p>状态引擎把增长、通胀、流动性、政策、信用与风险分开计算，再用证据和缺口说明当前结论有多可靠。</p></section>
    <Panel title={state.regime.label} eyebrow="CURRENT REGIME" aside={<Badge tone="warn">置信度 {Math.round(state.regime.confidence * 100)}%</Badge>}><div class="badge-row">{state.regime.tags.map((tag) => <Badge tone="info" key={tag}>{tag}</Badge>)}</div><p class="method-note">截至 {new Date(state.as_of).toLocaleString("zh-CN")}; 正值只表示该维度定义的方向更强，不等同于资产上涨。</p></Panel>
    <div class="state-card-grid">{Object.entries(state.dimensions).map(([key, item]) => <Panel title={key.replace("_", " ")} eyebrow="DIMENSION" key={key}><strong class={item.score !== null && item.score >= 0 ? "positive state-score" : "negative state-score"}>{item.score === null ? "—" : item.score.toFixed(2)}</strong><p class="muted">{item.direction} · 覆盖 {Math.round(item.coverage * 100)}% · 时效 {item.freshness == null ? "—" : `${Math.round(item.freshness * 100)}%`}</p>{item.top_drivers.slice(0, 2).map((driver) => <div class="driver-row" key={driver.series_key}><strong>{driver.title}</strong><span>{driver.latest_value == null ? "—" : driver.latest_value.toFixed(3)}</span></div>)}{item.missing_inputs.length ? <p class="method-note">缺口：{item.missing_inputs.slice(0, 2).join("；")}</p> : null}</Panel>)}</div>
    <Panel title="方法边界" eyebrow="METHOD"><ul class="boundary-list">{state.limitations.map((item) => <li key={item}>{item}</li>)}</ul></Panel>
  </div>;
}

