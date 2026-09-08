// Synthetic API responses are confined to an isolated browser context.
// No request reaches Research API and no research database is written.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root=path.resolve(__dirname,'..');
const port=4189;
const origin=`http://127.0.0.1:${port}`;
const base={data_mode:'observed',as_of:'2026-08-12T15:00:00Z',methodology_version:'test-only'};
const market=(key,label,unit='%')=>({key,label,symbol:key,asset_class:unit==='bp'?'rates':'metals',value:100,formatted_value:'100.00',change:-.5,change_unit:unit,direction:'down',trend:'down',status:'available',freshness:'STALE',proxy:false,derived:false,capabilities:{},sparkline:[99,101,100],chart_points:[{time:'2026-08-10',value:99},{time:'2026-08-11',value:101},{time:'2026-08-12',value:100}],horizons:Object.fromEntries(['1d','1w','1m','3m'].map(k=>[k,{value:-.5,unit,direction:'down'}])),details:{provider:'test-only',canonical_key:key,data_mode:'observed',quality:'test-only',timestamp:'2026-08-12T00:00:00Z',granularity_seconds:86400,limitation:'Synthetic browser test'}});
const markets={...base,items:[market('gold_gc','黄金'),market('ust2y_yield_context','美国 2Y','bp'),market('dollar_broad_context','美元')],limitations:[]};
const release=(id,title)=>({id,release_type:'US_CPI',title,country:'USA',period_label:'2026-07',scheduled_at:'2026-08-12T12:30:00Z',released_at:'2026-08-12T12:30:00Z',status:'released',data_mode:'observed',analysis_status:'not_run',reproducibility_status:null});
const releases=[release('test-cpi','美国 CPI'),release('test-second','第二个测试事件')];
const indicator={key:'headline_mom',label:'Headline CPI MoM',unit:'%',family:'inflation',hotter_when_higher:true};
const eventDetail=id=>({id,event:{...releases.find(r=>r.id===id),type:'US_CPI',source_timezone:'America/New_York'},supported_indicators:[indicator],expectations:{available:true,eligible_count:1,indicators:[{...indicator,consensus:.2,captured_at:'2026-08-11T12:00:00Z',source:'test-only',eligibility:'pre_t0'}]},actual:{available:true,indicators:[{...indicator,actual:.3,previous:.2,revised_previous:null,revision:null,source:'test-only'}]},surprise:{available:true,classification:'测试偏热',direction:'hot',score:null,indicators:[{...indicator,raw_surprise:.1,direction:'hot',surprise_z:null,sample_count:0,threshold_scaled_surprise:2}]},market_reaction:{available:false,status:'missing',matrix:[],available_assets:[],partial_assets:[],missing_assets:[{key:'gold_gc',label:'黄金',eligible:false,status:'missing',is_proxy:false}]},historical_context:{},analysis:{run_id:null,status:'not_run',data_gaps:[],confidence:null},actions:{can_run_analysis:false,analysis_blockers:['missing_eligible_event_minute_manifest']},source:{title:'test-only'},data_quality:[],data_provenance:[],contamination:{level:'unknown'}});
const country={key:'USA',label:'美国',status:'partial',available_dimensions:['inflation'],dimensions:{inflation:{label:'通胀',score:.2,direction:'mixed',momentum:null,confidence:.5,coverage:.5,drivers:[],missing:[]}},details:{limitations:[]}};
const macro={...base,countries:[country],comparison:[],divergence:[],context_cards:[],limitations:[]};
const countryDetail={...base,country,selected_dimension:null,key_series:[],markets:[],recent_releases:[],upcoming_releases:[],state_history:[],comparisons:[],limitations:[]};
const events={...base,items:releases,upcoming:[],recent:releases,default_event_id:'test-cpi',limitations:[]};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const server=spawn(process.execPath,[path.join(root,'node_modules/vite/bin/vite.js'),'preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:root,stdio:'ignore',windowsHide:true});
 let browser;
 try {
  for(let n=0;n<50;n++){try{if((await fetch(origin)).ok)break;}catch{}if(n===49)throw new Error('preview failed to start');await wait(100);}
  browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let offline=false,eventsFail=false,fixture=false,delayFirst=false,completed=false;
  const analysisRequests=[];
  await context.route('**/v2/**',async route=>{
   const p=new URL(route.request().url()).pathname;
   if(route.request().method()==='POST'){
    assert.equal(p,'/v2/releases/test-second/analysis-runs','Only the isolated analysis mock may receive writes');
    const key=route.request().headers()['idempotency-key'];
    assert.ok(key,'Analysis must have an idempotency key');analysisRequests.push(key);
    if(analysisRequests.length===1)return route.fulfill({status:503,json:{detail:'测试：研究服务暂时不可用'}});
    completed=true;return route.fulfill({json:{id:'test-run',status:'completed'}});
   }
   assert.equal(route.request().method(),'GET','No other write is allowed');
   if(offline)return route.abort('connectionfailed');
   if(eventsFail&&p==='/v2/product/events')return route.fulfill({status:503,json:{detail:'test event feed unavailable'}});
   if(delayFirst&&p==='/v2/product/events/test-cpi')await wait(1500);
   const value=p==='/v2/health'?{product:'worldstate-terminal',api_version:'v2',database:{status:'ok'}}:p==='/v2/product/markets'?{...markets,data_mode:fixture?'fixture':'observed'}:p==='/v2/product/events'?events:p.startsWith('/v2/product/events/')?{...eventDetail(p.split('/').at(-1)),...(completed?{analysis:{run_id:'test-run',status:'completed',confidence:.6,reproducibility:'complete',data_gaps:[]}}:{})}:p==='/v2/analysis-runs/test-run/claims'?{run_id:'test-run',items:[{claim_id:'valid',claim_type:'confirmed_fact',statement:'测试事实有证据',evidence_ids:['test-evidence'],confidence:.8,is_inference:false,limitations:['仅用于自动测试'],falsifier:null,validation:{valid:true}},{claim_id:'invalid',statement:'不应显示的未验证结论',validation:{valid:false}}]}:p.endsWith('/historical-matches')?{analysis_run_id:'test-run',pre_filter_count:2,post_filter_count:1,mode:'insufficient',similar_cases:[],metrics:{},filters:[]}:p==='/v2/product/macro'?macro:p==='/v2/product/macro/USA'?countryDetail:[];
   return route.fulfill({json:value});
  });
  const visible=async selector=>page.locator(selector).first().waitFor({state:'visible',timeout:8000});
  await page.goto(origin+'/#radar');await visible('.radar-ticker');
  assert.equal(await page.locator('nav[aria-label="主导航"] button').count(),4);
  assert.match(await page.locator('.reality-alert').innerText(),/不能回答/);
  await page.getByRole('button',{name:'学习',exact:true}).click();await page.getByRole('button',{name:'解释：实际利率'}).click();await visible('[role="note"]');
  console.log('PASS radar, data age, learning');
  await page.goto(origin+'/#markets');await page.getByRole('row').filter({hasText:'黄金'}).click();await visible('[role="dialog"] .investigation');
  await page.locator('[role="dialog"]').getByText('来源与研究详情',{exact:true}).click();await visible('[role="dialog"] .detail-grid');
  await page.keyboard.press('Escape');assert.equal(await page.locator('[role="dialog"]').count(),0);
  console.log('PASS market drilldown, source disclosure');
  await page.goto(origin+'/#macro');await page.locator('.matrix-table .link-button').click();await visible('[role="dialog"] .drawer-kpi');await page.keyboard.press('Escape');
  console.log('PASS country drilldown');
  await page.goto(origin+'/#events?release=test-cpi');await visible('.event-comparison');assert.match(await page.locator('.event-comparison').innerText(),/0\.2%/);assert.match(await page.locator('.event-comparison').innerText(),/0\.3%/);
  await page.getByRole('button',{name:'添加预期记录',exact:true}).click();await visible('[role="dialog"]');await page.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'跨资产反应',exact:true}).click();await visible('.minute-gap');assert.equal(await page.locator('.reaction-table').count(),0);
  await page.getByRole('button',{name:'导入分钟行情',exact:true}).click();await visible('.wizard-progress');await page.getByRole('button',{name:'取消',exact:true}).click();
  console.log('PASS merged event, consensus modal, honest minute gap, import entry');
  await page.goto(origin+'/#memory');await page.locator('.memory-list button').first().click();await visible('.event-comparison');
  await page.goBack();await visible('.memory-list');console.log('PASS memory and back navigation');
  await page.goto(origin+'/#radar');await visible('.radar-ticker');eventsFail=true;
  await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/事件刷新失败/).waitFor();assert.equal(await page.locator('.radar-ticker').count(),3);
  console.log('PASS partial API failure preserves market workspace');
  eventsFail=false;offline=true;await page.reload();await visible('.radar-ticker');await page.getByText(/市场刷新失败/).waitFor();assert.equal(await page.locator('nav button').count(),4);console.log('PASS offline reopen uses saved observed state');
  offline=false;fixture=true;await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/市场刷新失败/).waitFor();assert.equal(await page.locator('.radar-ticker').count(),3);fixture=false;
  console.log('PASS fixture response cannot overwrite observed cache');
  // A delayed older event response must not replace the event selected afterward.
  await page.goto(origin+'/#memory');delayFirst=true;await page.goto(origin+'/#events?release=test-cpi');await wait(100);await page.goto(origin+'/#events?release=test-second');await page.getByRole('heading',{name:'第二个测试事件',exact:true}).waitFor();await wait(1700);assert.equal(await page.locator('.event-reading-head h1').innerText(),'第二个测试事件');
  console.log('PASS event response race');
  delayFirst=false;
  await context.route('**/v2/product/events/test-second*',route=>route.fulfill({json:{...eventDetail('test-second'),actions:{can_run_analysis:true,analysis_blockers:[]},...(completed?{analysis:{run_id:'test-run',status:'completed',confidence:.6,reproducibility:'complete',data_gaps:[]}}:{})}}));
  await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByRole('button',{name:'解释与历史',exact:true}).click();
  await page.getByRole('button',{name:'生成本次复盘',exact:true}).click();await visible('[role="alert"]');
  await page.getByRole('button',{name:'生成本次复盘',exact:true}).click();
  await page.getByText('测试事实有证据',{exact:true}).waitFor();assert.equal(analysisRequests.length,2);assert.equal(analysisRequests[0],analysisRequests[1],'Retry must preserve the analysis identity');
  assert.equal(await page.getByText('不应显示的未验证结论',{exact:true}).count(),0);assert.match(await page.locator('.release-reading').innerText(),/筛选前 2 个，筛选后 1 个/);console.log('PASS analysis submission, failure/retry, validated claims and historical sample disclosure');
  fs.mkdirSync(path.join(root,'test-results'),{recursive:true});
  for(const size of [{width:1440,height:900},{width:1920,height:1080}]){await page.setViewportSize(size);await page.goto(origin+'/#radar');await visible('.radar-ticker');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(root,`test-results/radar-${size.width}.png`)});}
  assert.deepEqual(errors,[]);console.log('PASS desktop widths and no runtime page errors');
 } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
