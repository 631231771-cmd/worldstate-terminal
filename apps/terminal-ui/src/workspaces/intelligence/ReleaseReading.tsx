import {useEffect,useState} from 'preact/hooks';
import {api} from '../../api/client';
import {Badge,DetailsDisclosure} from '../../components/Primitives';
import type {HistoricalResponse,ResearchClaim} from '../../types';

export function PreReleaseGuide({type}:{type:string}) {
  const employment=/NFP/.test(type);
  const policy=/FOMC/.test(type);
  if(!employment&&!policy&&!/CPI/.test(type))return null;
  const rows=policy?[
    ['比预期更鹰派','先看声明与利率路径，再看短端、美元是否上行；黄金和成长股是否承压。'],
    ['比预期更鸽派','先看短端是否下行，再区分宽松支持和增长担忧。股票不一定上涨。'],
    ['声明与发布会冲突','分别核对两个阶段，不用整晚最终涨跌替代阶段反转。'],
  ]:employment?[
    ['就业与工资同时偏强','核对短端是否重定价、美元是否确认，再看黄金和股指。'],
    ['就业走弱但工资偏热','增长和通胀信号竞争，不能仅凭非农总量给出单一解释。'],
    ['明显前值修订','区分新增惊喜与修订；不同单位不能按数值大小直接比较。'],
  ]:[
    ['整体与核心同时偏热','核对短端与实际利率、美元，再看黄金与成长股是否反向。'],
    ['整体与核心同时偏冷','核对利率下行能否得到美元确认；股票还取决于增长担忧。'],
    ['整体、核心或月率年率冲突','先拆开四项指标。能源扰动与核心黏性可能指向不同路径。'],
  ];
  return <section class="pre-release-guide"><h3>发布前，看哪些分歧？</h3><p>条件性观察清单，不是预测，也不是系统获取到的市场预期。</p>{rows.map(([title,text])=><div key={title}><strong>{title}</strong><span>{text}</span></div>)}</section>;
}

/** Only validated structured claims are ordinary reading content. */
export function ReleaseReading({releaseId,runId,onEvent}:{releaseId:string;runId:string;onEvent:(id:string)=>void}) {
  const [claims,setClaims]=useState<ResearchClaim[]|null>(null);
  const [history,setHistory]=useState<HistoricalResponse|null>(null);
  const [errors,setErrors]=useState<string[]>([]);
  const [nonce,setNonce]=useState(0);
  useEffect(()=>{
    let active=true;setClaims(null);setHistory(null);setErrors([]);
    const fail=(e:unknown)=>{if(active)setErrors(old=>[...old,e instanceof Error?e.message:'读取失败']);};
    void api.claims(runId).then(r=>{if(r.run_id!==runId)throw new Error('研究记录不匹配，未显示解释。');if(active)setClaims(r.items.filter(c=>c.validation?.valid));}).catch(fail);
    void api.historical(releaseId).then(r=>{if(r.analysis_run_id!==runId)throw new Error('历史比较已属于另一运行，请刷新事件后重试。');if(active)setHistory(r);}).catch(fail);
    return()=>{active=false;};
  },[releaseId,runId,nonce]);
  return <section class="release-reading">
    {errors.length?<div class="inline-notice">部分研究记录未能加载。<button type="button" onClick={()=>setNonce(n=>n+1)}>重试</button><DetailsDisclosure label="读取原因">{errors.join('；')}</DetailsDisclosure></div>:null}
    {claims===null&&!errors.length?<p role="status">正在读取已保存的证据与解释…</p>:null}
    {claims?.map(c=><article class="claim-reading" key={c.claim_id}><Badge tone={c.is_inference?'warn':'info'}>{c.is_inference?'研究推断':c.claim_type==='confirmed_fact'?'已确认事实':'研究记录'}</Badge><p>{c.statement}</p>{c.limitations.length?<small>限制：{c.limitations.join('；')}</small>:null}{c.falsifier?<p class="claim-falsifier">反证条件：{c.falsifier}</p>:null}<DetailsDisclosure label={`证据引用 · ${c.evidence_ids.length} 条`}><p>{c.evidence_ids.join(' · ')||'未记录'}</p><small>本条置信度 {Math.round(c.confidence*100)}% · 来自当前研究运行的已校验记录</small></DetailsDisclosure></article>)}
    {claims?.length===0?<p class="inline-notice">当前运行没有通过校验的陈述，不以自由文本补充结论。</p>:null}
    {history?<><h3>历史上有哪些可比案例？</h3><p class="muted">筛选前 {history.pre_filter_count} 个，筛选后 {history.post_filter_count} 个。{history.mode==='insufficient'||history.mode==='case_studies'?'样本不足以支持稳定概率，先作为案例阅读。':'统计范围以各资产实际样本为准。'}</p>{history.similar_cases.filter(c=>!c.is_fixture).map(c=><button class="history-case-link" type="button" key={String(c.event_id)} onClick={()=>onEvent(String(c.event_id))}><span>{new Date(String(c.release_at)).toLocaleDateString()} · {String(c.classification??'历史案例')}</span><span>打开原事件 →</span></button>)}<DetailsDisclosure label="历史筛选条件与统计细节"><pre class="json-view">{JSON.stringify({filters:history.filters,metrics:history.metrics,warning:history.warning},null,2)}</pre></DetailsDisclosure></>:null}
  </section>;
}
