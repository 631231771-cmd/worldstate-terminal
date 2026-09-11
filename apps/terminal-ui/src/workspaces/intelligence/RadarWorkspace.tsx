import { useState } from 'preact/hooks';
import { Badge, Sparkline } from '../../components/Primitives';
import type { ReleaseSummary } from '../../types';
import type { ProductMarketItem } from '../../types/product';
import { changeLabel, focusMarkets, isCurrent, marketRole, ROLE_LABELS, sessionDate } from './marketContext';
import { MarketInvestigation } from './MarketInvestigation';

export function eventName(event: ReleaseSummary) { return ({US_CPI:'美国 CPI',US_NFP:'美国非农',US_FOMC:'美联储 FOMC'} as Record<string,string>)[event.release_type] ?? event.title; }
export function eventTime(at: string) { return new Date(at).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}); }
export function upcomingEvents(events: ReleaseSummary[], now = Date.now()) { return events.filter(e => e.status === 'scheduled' && Date.parse(e.scheduled_at) >= now).sort((a,b) => a.scheduled_at.localeCompare(b.scheduled_at)); }
export function recentEvents(events: ReleaseSummary[]) { return events.filter(e => e.status === 'released').sort((a,b) => (b.released_at ?? b.scheduled_at).localeCompare(a.released_at ?? a.scheduled_at)); }

export function RadarWorkspace({markets,events,onEvent,onData,advanced,learningMode}: {markets:ProductMarketItem[];events:ReleaseSummary[];onEvent:(id:string)=>void;onData:()=>void;advanced:boolean;learningMode:boolean}) {
  const [selectedKey,setSelectedKey] = useState(() => localStorage.getItem('worldstate.radar.asset') ?? '');
  const focused = focusMarkets(markets);
  const selected = markets.find(i => i.key === selectedKey) ?? focused[0];
  const select = (item: ProductMarketItem) => {setSelectedKey(item.key);localStorage.setItem('worldstate.radar.asset',item.key);};
  const current = focused.filter(i => isCurrent(i));
  const dates = focused.map(sessionDate).filter((d):d is string=>!!d).sort();
  const next = upcomingEvents(events).slice(0,3);
  const recent = recentEvents(events).slice(0,3);
  return <div class="intelligence-workspace">
    <header class="radar-heading"><div><span class="section-label">MARKET INTELLIGENCE</span><h1>先看变化，再找解释。</h1></div><time>{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</time></header>
    {!current.length ? <div class="reality-alert"><div><strong>当前没有足够新的行情，不能回答“刚刚发生了什么”。</strong><span>{dates.length ? `本地日线覆盖至 ${dates.at(-1)}。以下保留最近记录，供历史核对。` : '先接入可信行情，再进行跨资产核对。'}</span></div><button type="button" onClick={onData}>检查数据更新 →</button></div> : <div class="observation-line">最近有效交易日变化 · {current.length} 项时效合格 · 日线背景，不是实时异动监控</div>}
    <div class="radar-market-strip" aria-label="关注市场">{focused.slice(0,9).map(item => <button type="button" key={item.key} class={selected?.key===item.key?'radar-ticker active':'radar-ticker'} onClick={()=>select(item)}><span>{ROLE_LABELS[marketRole(item)!]}</span><strong>{item.formatted_value}</strong><span class={item.change != null && item.change < 0 ? 'move-down':'move-up'}>{changeLabel(item)}</span><Sparkline values={item.sparkline} /><small>{sessionDate(item) ?? '缺失'}{!isCurrent(item)?' · 较旧':''}{item.proxy?' · 代理':''}</small></button>)}</div>
    <div class="radar-columns"><section class="radar-main">{selected ? <MarketInvestigation item={selected} markets={markets} onOpen={select} advanced={advanced} compact learningMode={learningMode}/> : <div class="inline-empty"><h2>先选择一个市场</h2><p>行情加载后，可以在这里核对利率、美元与风险资产。</p><button type="button" onClick={onData}>检查数据源</button></div>}</section>
    <aside class="radar-agenda"><div class="section-heading"><h2>下一件重要的事</h2><span>本机时区</span></div>{next.length ? next.map(event=><button type="button" key={event.id} class="agenda-event" onClick={()=>onEvent(event.id)}><time>{eventTime(event.scheduled_at)}</time><strong>{eventName(event)}</strong><span>{event.period_label} <b>查看预期 →</b></span></button>) : <div class="inline-empty"><p>本地日历中没有未来事件。</p><button type="button" onClick={onData}>更新官方日历 →</button></div>}
      <div class="section-heading"><h2>最近发布 · 待复盘</h2></div>{recent.map(event=><button type="button" key={event.id} class="agenda-event" onClick={()=>onEvent(event.id)}><time>{eventTime(event.scheduled_at)}</time><strong>{eventName(event)}</strong><span>{event.analysis_status==='completed'?'查看已有分析':'查看预期差 / 补齐反应'} →</span></button>)}{!recent.length?<p class="muted">尚无已发布记录。</p>:null}
      <div class="research-prompt"><Badge>研究顺序</Badge><h3>价格一起动，不等于原因已确认。</h3><p>先核对日期和频率，再查官方事件与预期差；最后看反证与历史案例。</p><small>右侧事件按发布时间排列，不代表它导致了左侧行情。</small></div>
    </aside></div>
  </div>;
}
