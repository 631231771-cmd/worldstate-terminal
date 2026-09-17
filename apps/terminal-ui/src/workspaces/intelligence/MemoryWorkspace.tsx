import { useState } from 'preact/hooks';
import type { ReleaseSummary } from '../../types';
import { ResearchWorkspace } from '../research/ResearchWorkspace';
import { eventName, eventTime, recentEvents } from './RadarWorkspace';

export function MemoryWorkspace({events,onEvent,selectedThesis,onThesis}: {events:ReleaseSummary[];onEvent:(id:string)=>void;selectedThesis:string|null;onThesis:(id:string)=>void}) {
  const [tab,setTab] = useState(selectedThesis ? 'notes' : 'events');
  const [query,setQuery] = useState('');
  const [completedOnly,setCompletedOnly] = useState(false);
  const rows = recentEvents(events).filter(e=>(!completedOnly || e.analysis_status==='completed') && `${eventName(e)} ${e.period_label}`.toLowerCase().includes(query.toLowerCase()));
  return <div class="intelligence-workspace"><header class="section-heading"><div><span class="section-label">RESEARCH MEMORY</span><h1>让每次研究留下来</h1></div></header><div class="tabs-bar"><button type="button" class={tab==='events'?'active':''} onClick={()=>setTab('events')}>事件档案</button><button type="button" class={tab==='notes'?'active':''} onClick={()=>setTab('notes')}>我的判断</button></div>
    {tab==='notes'?<ResearchWorkspace selectedId={selectedThesis} onSelect={onThesis}/>:<><div class="memory-filter"><input aria-label="搜索事件档案" placeholder="查找 CPI、非农、月份…" value={query} onInput={e=>setQuery(e.currentTarget.value)}/><label><input type="checkbox" checked={completedOnly} onChange={e=>setCompletedOnly(e.currentTarget.checked)}/>只看已有分析</label></div><p class="muted">发布记录自动留在档案中。只有实际运行过的分析才会显示为已复盘。</p><div class="memory-list">{rows.map(e=><button type="button" key={e.id} onClick={()=>onEvent(e.id)}><time>{eventTime(e.scheduled_at)}</time><strong>{eventName(e)}<small>{e.period_label}</small></strong><span>{e.classification ?? '预期差待查看'}</span><span>{e.analysis_status==='completed'?'已复盘':'反应待补齐'}</span><b>打开 →</b></button>)}</div>{!rows.length?<div class="inline-empty"><h3>还没有匹配的复盘</h3><p>可以取消筛选，打开发布记录查看已有数据与下一步。</p></div>:null}</>}
  </div>;
}
