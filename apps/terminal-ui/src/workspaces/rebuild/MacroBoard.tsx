import { useState } from "preact/hooks";
import type { ProductCountry, ProductTodayResponse } from "../../types/product";
import { Badge, DetailsDisclosure, Panel } from "../../components/Primitives";

const DIMENSIONS = ["growth", "inflation", "policy_tightness", "liquidity", "credit", "risk"] as const;

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
  return <button type="button" class="matrix-cell" onClick={onOpen}>
    <strong>{value?.score == null ? "—" : value.score.toFixed(2)}</strong>
    <span>{value?.score == null ? "缺失" : directionLabel(value.direction)}</span>
  </button>;
}

export function MacroBoard({ countries, onOpenCountry }: { countries: ProductCountry[]; onOpenCountry: (country: ProductCountry) => void }) {
  const [selected, setSelected] = useState<ProductCountry | null>(null);
  const active = selected ?? countries[0] ?? null;
  return <div class="workspace workspace--product">
    <section class="page-heading page-heading--compact"><div><div class="eyebrow">MACRO / GLOBAL MATRIX</div><h1>全球宏观矩阵</h1><p>只显示本地真实序列能够支持的国家与维度；较旧数据会明确标记。</p></div><div class="page-heading__aside"><Badge tone="info">{countries.filter((item) => item.available_dimensions.length > 0).length} 个经济体有数据</Badge></div></section>
    <Panel title="全球状态" eyebrow="GROWTH / INFLATION / POLICY / LIQUIDITY / CREDIT / RISK">
      <div class="table-wrap"><table class="matrix-table"><thead><tr><th>国家 / 地区</th>{DIMENSIONS.map((dimension) => <th key={dimension}>{countries[0]?.dimensions[dimension]?.label ?? dimension}</th>)}</tr></thead><tbody>{countries.map((country) => <tr key={country.key}><td><button type="button" class="link-button" onClick={() => { setSelected(country); onOpenCountry(country); }}><strong>{country.label}</strong><small class="muted">{statusLabel(country.status)}</small></button></td>{DIMENSIONS.map((dimension) => <td key={dimension}><CountryCell country={country} dimension={dimension} onOpen={() => { setSelected(country); onOpenCountry(country); }} /></td>)}</tr>)}</tbody></table></div>
    </Panel>
    {active ? <Panel title={`${active.label} · 当前状态`} eyebrow="COUNTRY DETAIL" aside={<Badge tone={active.status === "available" ? "good" : active.status === "partial" || active.status === "stale" ? "warn" : "neutral"}>{statusLabel(active.status)}</Badge>}><div class="board-grid board-grid--markets">{Object.entries(active.dimensions).map(([dimension, value]) => <button type="button" class="metric-tile" key={dimension} onClick={() => onOpenCountry(active)}><span class="metric-tile__label">{value.label}</span><strong class="metric-tile__value">{value.score == null ? "—" : value.score.toFixed(2)}</strong><span class="metric-tile__meta">{directionLabel(value.direction)} / 置信度 {Math.round(value.confidence * 100)}%</span></button>)}</div><DetailsDisclosure label="数据边界"><p class="method-note">{active.details.limitations.join(" ") || "基于本地 Series 与 Observation 计算。"}</p></DetailsDisclosure></Panel> : <Panel title="选择国家" eyebrow="COUNTRY DETAIL"><p class="muted">点击矩阵中的国家继续研究。</p></Panel>}
  </div>;
}

export function ProductMacroFromToday({ data, onOpenCountry }: { data: ProductTodayResponse; onOpenCountry: (country: ProductCountry) => void }) { return <MacroBoard countries={data.global} onOpenCountry={onOpenCountry} />; }
