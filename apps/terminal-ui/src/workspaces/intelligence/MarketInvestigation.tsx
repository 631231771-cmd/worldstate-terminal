import { useState } from 'preact/hooks';
import { Badge, DetailsDisclosure } from '../../components/Primitives';
import { ConceptStrip } from '../../components/ConceptHelp';
import { TimeSeriesChart, type ChartHorizon } from '../../components/TimeSeriesChart';
import type { ProductMarketItem } from '../../types/product';
import { changeLabel, checkPath, CONTEXT_PATHS, isCurrent, marketRole, ROLE_LABELS, sessionDate } from './marketContext';

export function MarketInvestigation({ item, markets, onOpen, advanced = false, compact = false, learningMode = false }: {item: ProductMarketItem; markets: ProductMarketItem[]; onOpen: (item: ProductMarketItem) => void; advanced?: boolean; compact?: boolean; learningMode?: boolean}) {
  const [pathKey, setPathKey] = useState('rates');
  const [horizon, setHorizon] = useState<ChartHorizon>('1m');
  const path = CONTEXT_PATHS.find(p => p.key === pathKey)!;
  const checks = checkPath(path, markets, item);
  const hasComparable = checks.some(row => ['agrees','opposes','flat'].includes(row.state));
  const chart = (item.chart_points?.length ?? 0) > 1 ? <><div class="chart-horizons">{(['1w','1m','3m','1y'] as ChartHorizon[]).map(h => <button key={h} type="button" class={h === horizon ? 'active' : ''} onClick={() => setHorizon(h)}>{h.toUpperCase()}</button>)}</div><TimeSeriesChart points={item.chart_points ?? []} horizon={horizon} /></> : <p class="inline-notice">尚无连续历史，不能绘制可信趋势。</p>;
  return <div class="investigation" data-testid="market-investigation">
    <header class="investigation-head"><div><span class="section-label">正在核对</span><h2>{ROLE_LABELS[marketRole(item)!] ?? item.label}</h2></div><div class="market-reading"><strong>{item.formatted_value}</strong><span>{changeLabel(item)}</span></div></header>
    <div class="observation-line"><span>最近有效日线 · {sessionDate(item) ?? '无时间记录'}</span>{!isCurrent(item) ? <Badge tone="warn">数据较旧 · 不能解释此刻波动</Badge> : <Badge>非实时行情</Badge>}{item.proxy ? <Badge tone="warn">代理资产</Badge> : null}</div>
    {compact ? null : chart}
    <div class="section-heading"><h3>市场可能在交易什么？</h3><span>待验证路径，不是事件归因</span></div>
    <ConceptStrip concepts={['real_yield','inflation','liquidity']} active={learningMode}/>
    <div class="path-tabs" aria-label="传导路径">{CONTEXT_PATHS.map(p => <button type="button" key={p.key} class={p.key === pathKey ? 'active' : ''} onClick={() => setPathKey(p.key)}>{p.label}</button>)}</div>
    <ol class="transmission-chain">{path.chain.map((step,i) => <li key={step}><small>{i+1}</small>{step}</li>)}</ol>
    <div class="confirmation-table"><div class="confirmation-head"><span>核对市场</span><span>路径所需方向</span><span>最近日变化</span><span>方向核对</span></div>{checks.map(row => <button key={row.role} type="button" disabled={!row.item} class="confirmation-row" onClick={() => row.item && onOpen(row.item)}><strong>{ROLE_LABELS[row.role]}{row.item?.proxy ? <small>代理</small> : null}</strong><span>{row.expected > 0 ? '↑ 上行' : '↓ 下行'}</span><span>{row.item ? changeLabel(row.item) : '—'}<small>{row.item ? sessionDate(row.item) : '暂无数据'}</small></span><span class={`confirmation-${row.state}`}>{{agrees:'方向一致',opposes:'方向相反',flat:'无明显方向',unconfirmed:'无法核对',missing:'缺少数据'}[row.state]}</span></button>)}</div>
    <p class="comparison-limit">{hasComparable ? '仅比较同日、同粒度的日变化；不同市场收盘时刻仍可能不同，不代表盘中同步或因果确认。' : '日期、时效或粒度不满足可比条件，暂不作方向确认。日线不能回答刚刚哪项资产先动。'}</p>
    <div class="path-caution"><p>{path.note}</p><p><strong>什么会推翻这条解释：</strong>{path.falsifier}</p></div>
    {compact ? <DetailsDisclosure label="查看价格轨迹">{chart}</DetailsDisclosure> : null}
    <DetailsDisclosure label="来源与研究详情"><dl class="detail-grid"><div><dt>来源</dt><dd>{item.details.provider ?? '未记录'}</dd></div><div><dt>观测时间</dt><dd>{item.details.timestamp ?? '未记录'}</dd></div><div><dt>限制</dt><dd>{item.details.limitation ?? '日线背景，不用于分钟事件归因'}</dd></div></dl>{advanced ? <pre class="json-view">{JSON.stringify({details:item.details,capabilities:item.capabilities},null,2)}</pre> : null}</DetailsDisclosure>
  </div>;
}
