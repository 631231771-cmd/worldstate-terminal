import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Panel, StateMessage } from "../../components/Primitives";

export function CountriesWorkspace() {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { void api.globalMacro().then(setPayload).catch(() => setPayload(null)); }, []);
  if (!payload) return <StateMessage title="全球层暂不可用" detail="研究服务没有返回国家概览。" />;
  const countries = (payload.countries as Array<Record<string, unknown>>) ?? [];
  return <div class="workspace"><section class="page-heading"><div class="eyebrow">GLOBAL MACRO · CONTEXT LAYER</div><h1>全球宏观第一层</h1><p>先覆盖美国、中国、欧元区、日本和英国；状态来自已登记的 Series/Observation，覆盖不足就明确显示 unavailable。</p></section><div class="country-grid">{countries.map((country) => <Panel title={String(country.name)} eyebrow={String(country.iso2)} key={String(country.iso3)} aside={<Badge tone={country.status === "available" ? "good" : "warn"}>{String(country.status)}</Badge>}><div class="country-dimensions">{Object.entries((country.dimensions as Record<string, unknown>) ?? {}).map(([key, value]) => <div class="driver-row" key={key}><strong>{key}</strong><span>{String((value as Record<string, unknown>).value ?? "—")}</span></div>)}</div><p class="method-note">{country.latest_data_at ? `最新数据 ${String(country.latest_data_at)}` : "尚无可用数据"}</p>{((country.limitations as string[]) ?? []).map((item) => <p class="method-note" key={item}>{item}</p>)}</Panel>)}</div><Panel title="Context Layer" eyebrow="FRAMEWORK"><div class="context-cards">{((payload.context_cards as Array<Record<string, unknown>>) ?? []).map((card) => <div class="context-card" key={String(card.key)}><strong>{String(card.title)}</strong><Badge tone={card.status === "framework" ? "warn" : "info"}>{String(card.status)}</Badge><p>{((card.components as string[]) ?? []).join(" · ")}</p></div>)}</div><ul class="boundary-list">{((payload.limitations as string[]) ?? []).map((item) => <li key={item}>{item}</li>)}</ul></Panel></div>;
}

