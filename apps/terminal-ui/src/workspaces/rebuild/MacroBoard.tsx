import { useState } from "preact/hooks";
import type { ProductCountry, ProductMacroResponse } from "../../types/product";
import { Badge, DetailsDisclosure, Panel } from "../../components/Primitives";

const DIMENSIONS = ["growth", "inflation", "policy_tightness", "liquidity", "credit", "risk"] as const;
const DIMENSION_LABELS: Record<string, string> = {
  growth: "增长",
  inflation: "通胀",
  policy_tightness: "政策约束",
  liquidity: "流动性",
  credit: "信用",
  risk: "风险",
  external: "外部",
  fiscal: "财政",
};

function statusLabel(status: string) {
  if (status === "available") return "可用";
  if (status === "partial") return "部分覆盖";
  if (status === "stale") return "数据较旧";
  return "缺失";
}

function directionLabel(direction: string) {
  if (direction === "strong") return "偏强";
  if (direction === "weak") return "偏弱";
  if (direction === "mixed") return "分化";
  return "缺失";
}

function CountryCell({ country, dimension, onOpen }: { country: ProductCountry; dimension: string; onOpen: () => void }) {
  const value = country.dimensions[dimension];
  const missing = value?.score == null;
  return <button type="button" class={missing ? "matrix-cell matrix-cell--missing" : "matrix-cell"} onClick={onOpen}>
    <strong>{missing ? "—" : value.score?.toFixed(2)}</strong>
    <span>{missing ? "缺失" : directionLabel(value.direction)}</span>
  </button>;
}

export function MacroBoard({ data, selectedCountryKey, onOpenCountry }: { data: ProductMacroResponse; selectedCountryKey?: string | null; onOpenCountry: (country: ProductCountry, dimension?: string) => void }) {
  const [selected, setSelected] = useState<ProductCountry | null>(null);
  const active = data.countries.find((item) => item.key === selectedCountryKey) ?? selected ?? data.countries[0] ?? null;
  return <div class="workspace workspace--product">
    <section class="page-heading page-heading--compact">
      <div><div class="eyebrow">MACRO / GLOBAL MATRIX</div><h1>全球宏观矩阵</h1><p>只比较本地真实序列支持的国家与维度；缺失、较旧和部分覆盖不会被自动补齐。</p></div>
      <div class="page-heading__aside"><Badge tone="info">{data.countries.filter((item) => item.available_dimensions.length > 0).length} 个经济体有数据</Badge></div>
    </section>
    <Panel title="全球状态" eyebrow="GROWTH / INFLATION / POLICY / LIQUIDITY / CREDIT / RISK">
      <div class="table-wrap"><table class="matrix-table"><thead><tr><th>国家 / 地区</th>{DIMENSIONS.map((dimension) => <th key={dimension}>{DIMENSION_LABELS[dimension]}</th>)}</tr></thead><tbody>{data.countries.map((country) => <tr key={country.key}><td><button type="button" class="link-button" onClick={() => { setSelected(country); onOpenCountry(country); }}><strong>{country.label}</strong><small class="muted">{statusLabel(country.status)}</small></button></td>{DIMENSIONS.map((dimension) => <td key={dimension}><CountryCell country={country} dimension={dimension} onOpen={() => { setSelected(country); onOpenCountry(country, dimension); }} /></td>)}</tr>)}</tbody></table></div>
    </Panel>
    {active ? <Panel title={`${active.label} · 当前状态`} eyebrow="COUNTRY OVERVIEW" aside={<Badge tone={active.status === "available" ? "good" : active.status === "partial" || active.status === "stale" ? "warn" : "neutral"}>{statusLabel(active.status)}</Badge>}>
      <div class="board-grid board-grid--markets">{Object.entries(active.dimensions).map(([dimension, value]) => <button type="button" class="metric-tile" key={dimension} onClick={() => onOpenCountry(active, dimension)}><span class="metric-tile__label">{value.label || DIMENSION_LABELS[dimension] || dimension}</span><strong class="metric-tile__value">{value.score == null ? "—" : value.score.toFixed(2)}</strong><span class="metric-tile__meta">{directionLabel(value.direction)} · 置信度 {Math.round(value.confidence * 100)}%</span></button>)}</div>
      <DetailsDisclosure label="数据边界"><p class="method-note">{active.details.limitations.join(" ") || "基于本地 Series 与 Observation 按时点计算。"}</p></DetailsDisclosure>
    </Panel> : null}
    {data.divergence.length ? <Panel title="跨经济体分化" eyebrow="RELATIVE STATE / NOT CAUSALITY"><div class="research-list research-list--compact">{data.divergence.slice(0, 4).map((item) => <button type="button" class="research-row" key={item.dimension} onClick={() => { const country = data.countries.find((row) => row.key === item.stronger.iso3); if (country) onOpenCountry(country, item.dimension); }}><div><strong>{DIMENSION_LABELS[item.dimension] ?? item.dimension}</strong><span>{data.countries.find((row) => row.key === item.stronger.iso3)?.label ?? item.stronger.iso3} 相对偏强，{data.countries.find((row) => row.key === item.weaker.iso3)?.label ?? item.weaker.iso3} 相对偏弱</span></div><Badge tone="info">差值 {item.spread.toFixed(2)}</Badge></button>)}</div></Panel> : null}
  </div>;
}
