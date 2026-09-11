const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const Module = require('node:module');
// Pure domain/presentation policies: compile the actual source, not a copied implementation.
function load(relative) {
 const file=path.resolve(__dirname,'../src',relative);
 const result=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}});
 const m=new Module(file,module);m.filename=file;m.paths=module.paths;m._compile(result.outputText,file);return m.exports;
}
const cache=load('app/resourceCache.ts');const nav=load('app/navigation.ts');const ctx=load('workspaces/intelligence/marketContext.ts');
function storage(){const data=new Map();return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};}
test('read cache keeps successful observed data across reopen',()=>{
 const s=storage();cache.saveCached(s,'local','markets',{data_mode:'observed',items:[{value:5}]});
 assert.equal(cache.readCached(s,'local','markets').value.items[0].value,5);
 assert.equal(cache.readCached(s,'other-api','markets'),null);
 assert.equal(cache.readCached(s,'local','other-event'),null);
});
test('fixture or unclassified responses never replace observed cache',()=>{
 const s=storage();cache.saveCached(s,'x','y',{data_mode:'observed',value:42});
 for(const v of [{data_mode:'fixture'},{items:[]},{data_mode:'observed',items:[{data_mode:'fixture'}]},{event:{data_mode:'observed'},quality:[{is_fixture:true}]}])assert.throws(()=>cache.saveCached(s,'x','y',v));
 assert.equal(cache.readCached(s,'x','y').value.value,42);
});
test('corrupt and future-invalid saved timestamps fail closed',()=>{
 const s=storage();s.setItem(cache.readKey('x','y'),'broken');assert.equal(cache.readCached(s,'x','y'),null);
 s.setItem(cache.readKey('x','y'),JSON.stringify({value:{data_mode:'observed'},savedAt:'not-a-date'}));assert.equal(cache.readCached(s,'x','y'),null);
});
test('quota error does not discard the fresh in-memory read',()=>{
 const s={...storage(),setItem:()=>{throw new Error('quota');}};
 assert.equal(cache.saveCached(s,'x','y',{event:{data_mode:'observed'},value:7}).value.value,7);
});
test('routes retain old links and new primary workflow',()=>{
 assert.equal(nav.parseRoute('#radar').view,'today');assert.equal(nav.parseRoute('#memory').view,'research');
 assert.equal(nav.parseRoute('#event-lab?release=abc').params.get('release'),'abc');assert.equal(nav.parseRoute('#calendar').view,'events');
 assert.equal(nav.NAV.length,4);assert.equal(nav.NAV.some(i=>i.key==='data-control'),false);
});
test('default event favors available research then most recent released then nearest future',()=>{
 const event=(id,status,time,analysis_status='not_run')=>({id,status,scheduled_at:time,analysis_status,reproducibility_status:'complete'});
 const future=event('future','scheduled','2028-01-01');const next=event('next','scheduled','2026-10-01');const recent=event('recent','released','2026-08-12');const run=event('run','released','2026-07-01','completed');
 const now=Date.parse('2026-09-05');assert.equal(nav.preferredRelease([future,next],now).id,'next');assert.equal(nav.preferredRelease([future,recent,next],now).id,'recent');assert.equal(nav.preferredRelease([recent,run],now).id,'run');
});
const now=Date.parse('2026-09-05T12:00:00Z');
function market(key,change,extra={}){return {key,label:key,symbol:key,change,change_unit:key.includes('yield')?'bp':'%',status:'available',freshness:'AVAILABLE',details:{timestamp:'2026-09-04T00:00:00Z',granularity_seconds:86400,data_mode:'observed'},...extra};}
test('rate pathway shows agreement AND competing price evidence without causal score',()=>{
 const gold=market('gold_gc',-1),rates=market('ust2y_yield_context',5),usd=market('dollar_broad_context',-.3);
 const rows=ctx.checkPath(ctx.CONTEXT_PATHS[0],[gold,rates,usd],gold,now);
 assert.equal(rows.find(i=>i.role==='gold').state,'agrees');assert.equal(rows.find(i=>i.role==='rates2').state,'agrees');assert.equal(rows.find(i=>i.role==='dollar').state,'opposes');
 assert.equal(rows.find(i=>i.role==='real').state,'missing');
});
test('stale, different-day, minute, future and fixture readings are not confirmation',()=>{
 const gold=market('gold_gc',-1);const usd=market('dollar_broad_context',1);
 for(const bad of [{...usd,freshness:'STALE'},{...usd,details:{...usd.details,timestamp:'2026-09-03T00:00:00Z'}},{...usd,details:{...usd.details,granularity_seconds:60}},{...usd,details:{...usd.details,data_mode:'fixture'}},{...usd,details:{...usd.details,timestamp:'2026-09-06T00:00:00Z'}}])assert.equal(ctx.checkPath(ctx.CONTEXT_PATHS[0],[gold,bad],gold,now).find(i=>i.role==='dollar').state,'unconfirmed');
 assert.equal(ctx.isCurrent({...gold,details:{...gold.details,timestamp:'2026-08-12T00:00:00Z'}},now),false);
});
test('futures price changes are never interpreted as cash yield basis points',()=>{
 const gold=market('gold_gc',-1);const rates=market('ust2y_zt',1,{change_unit:'%'});
 assert.equal(ctx.checkPath(ctx.CONTEXT_PATHS[0],[gold,rates],gold,now).find(i=>i.role==='rates2').state,'unconfirmed');
});
test('market focus includes actual dollar identity and stable priority',()=>{
 const rows=ctx.focusMarkets([market('hy_spread_context',1),market('dollar_broad_context',1),market('gold_gc',1)]);
 assert.equal(rows[0].key,'gold_gc');assert.equal(ctx.marketRole(rows[1]),'dollar');
});
test('WTI identity never aliases Brent because both Chinese labels contain crude oil',()=>{
 const brent=market('brent_spot',7,{label:'布伦特原油',symbol:'BRENT'});
 const wti=market('wti_spot',5,{label:'WTI 原油',symbol:'WTI'});
 assert.equal(ctx.marketRole(brent),undefined);
 assert.equal(ctx.focusMarkets([brent,wti]).find(row=>ctx.marketRole(row)==='oil').key,'wti_spot');
 assert.equal(ctx.checkPath(ctx.CONTEXT_PATHS[3],[brent,wti],wti,now)[0].item.key,'wti_spot');
});
