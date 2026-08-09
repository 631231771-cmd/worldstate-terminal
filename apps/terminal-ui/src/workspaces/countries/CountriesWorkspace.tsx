import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

type MacroCountry = {
  iso3: string;
  iso2: string;
  name: string;
  status: string;
  dimensions: Record<string, { score: number | null; direction: string; momentum: number | null; confidence: number; coverage: number; freshness: number | null }>;
  latest_data_at: string | null;
  limitations: string[];
};

export function CountriesWorkspace() {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [systems, setSystems] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { void Promise.all([api.globalMacro(), api.macroSystems()]).then(([global, macroSystems]) => { setPayload(global); setSystems(macroSystems); }).catch(() => setPayload(null)); }, []);
  if (!payload) return <StateMessage title="全球层暂不可用" detail="研究服务没有返回国家宏观状态。" />;
  const countries = (payload.countries as MacroCountry[]) ?? [];
  const divergence = (payload.divergence as Array<Record<string, unknown>>) ?? [];
  return <div class="workspace">
    <section class="page-heading"><div><div class="eyebrow">GLOBAL MACRO · COMPARISON</div><h1>全球宏观比较</h1><p>状态来自真实 Series/Observation；没有数据的经济体保持 unavailable，不用标签伪装覆盖。</p></div></section>
    <div class="country-grid">{countries.map((country) => <Panel title={country.name} eyebrow={country.iso2} key={country.iso3} aside={<Badge tone={country.status === "available" ? "good" : "warn"}>{country.status}</Badge>}>
      <div class="country-dimensions">{Object.entries(country.dimensions).map(([key, value]) => <div class="driver-row" key={key}><strong>{key}</strong><span>{value.score == null ? "—" : value.score.toFixed(2)} · {value.direction}</span></div>)}</div>
      <p class="method-note">{country.latest_data_at ? `最新可用：${country.latest_data_at}` : "尚无符合条件的观测"}</p>
      {country.limitations.map((item) => <p class="method-note" key={item}>{item}</p>)}
    </Panel>)}</div>
    <Panel title="Macro Divergence" eyebrow="RELATIVE STATE SPREAD"><div class="divergence-list">{divergence.slice(0, 12).map((item) => <article class="context-card" key={String(item.dimension)}><strong>{String(item.dimension)}</strong><p>{String((item.stronger as Record<string, unknown>)?.name ?? "—")} ↔ {String((item.weaker as Record<string, unknown>)?.name ?? "—")}</p><Badge tone="info">spread {Number(item.spread ?? 0).toFixed(2)}</Badge><small>相对状态差异，不是单一因果结论</small></article>)}</div></Panel>
    <Panel title="Global Systems" eyebrow="LIQUIDITY · RATES · DOLLAR · ENERGY"><div class="context-cards">{((payload.context_cards as Array<Record<string, unknown>>) ?? []).map((card) => <div class="context-card" key={String(card.key)}><strong>{String(card.title)}</strong><Badge tone={card.status === "available" ? "good" : "warn"}>{String(card.status)}</Badge><p>{((card.components as string[]) ?? []).join(" · ")}</p></div>)}</div><ul class="boundary-list">{((payload.limitations as string[]) ?? []).map((item) => <li key={item}>{item}</li>)}</ul></Panel>
    {systems ? <Panel title="系统组件" eyebrow="TRANSPARENT COMPONENTS"><div class="context-cards">{((systems.systems as Array<Record<string, unknown>>) ?? []).map((system) => <div class="context-card" key={String(system.key)}><strong>{String(system.title)}</strong><Badge tone={system.status === "available" ? "good" : "warn"}>{String(system.status)} · {Math.round(Number(system.coverage ?? 0) * 100)}%</Badge><p>{((system.components as Array<Record<string, unknown>>) ?? []).filter((component) => component.status === "available").map((component) => `${String(component.title)} ${component.latest_value ?? "—"}`).join(" · ") || "暂无组件观测"}</p></div>)}</div></Panel> : null}
  </div>;
}
