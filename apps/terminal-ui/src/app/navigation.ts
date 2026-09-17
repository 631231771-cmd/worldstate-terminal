import type { ReleaseSummary } from '../types';
export type ProductView = 'today'|'events'|'markets'|'macro'|'research'|'data-control'|'data-methods';
export const NAV = [
  {key:'today' as const,label:'雷达',note:'变化与解释'},
  {key:'events' as const,label:'事件台',note:'预期到反应'},
  {key:'markets' as const,label:'市场脉络',note:'跨资产与宏观'},
  {key:'research' as const,label:'研究记忆',note:'复盘与判断'},
];
export function parseRoute(hash:string) {
  const [name='',query=''] = hash.replace(/^#/,'').split('?');
  const aliases:Record<string,ProductView>={radar:'today',memory:'research','cross-asset':'markets','world-state':'macro',countries:'macro',series:'macro','event-lab':'events',releases:'events',calendar:'events'};
  const accepted:ProductView[]=['today','markets','macro','events','research','data-control','data-methods'];
  return {view: accepted.includes(name as ProductView)?name as ProductView:aliases[name]??'today',params:new URLSearchParams(query)};
}
export function preferredRelease(items:ReleaseSummary[],now=Date.now()):ReleaseSummary|null {
  const released=items.filter(i=>i.status==='released').sort((a,b)=>(b.released_at??b.scheduled_at).localeCompare(a.released_at??a.scheduled_at));
  return released.find(i=>i.analysis_status==='completed'&&i.reproducibility_status==='complete')??released[0]??items.filter(i=>Date.parse(i.scheduled_at)>=now).sort((a,b)=>a.scheduled_at.localeCompare(b.scheduled_at))[0]??null;
}
