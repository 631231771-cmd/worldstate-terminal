import type { ProductMarketItem } from '../../types/product';

export type MarketRole = 'gold' | 'silver' | 'oil' | 'rates2' | 'rates10' | 'real' | 'dollar' | 'equity' | 'nasdaq' | 'vix' | 'credit' | 'btc';
const patterns: Array<[MarketRole, RegExp]> = [
  ['gold', /gold|黄金|\bGC\b/i], ['silver', /silver|白银/i], ['oil', /wti|西德克萨斯|\bCL\b/i],
  ['real', /real.yield|实际.*收益/i], ['rates2', /ust2y|美国 2Y/i], ['rates10', /ust10y|美国 10Y/i],
  ['dollar', /broad.*dollar|dollar_broad|broad_usd|广义美元|美元指数/i], ['nasdaq', /nasdaq|纳斯达克/i],
  ['equity', /sp500|标普/i], ['vix', /vix/i], ['credit', /high.yield|高收益利差/i], ['btc', /btc|bitcoin|比特币/i],
];
export function marketRole(item: ProductMarketItem): MarketRole | undefined {
  return patterns.find(([, regex]) => regex.test(`${item.key} ${item.label} ${item.symbol ?? ''}`))?.[0];
}
export const ROLE_LABELS: Record<MarketRole, string> = {gold:'黄金',silver:'白银',oil:'WTI 原油',rates2:'美国 2Y',rates10:'美国 10Y',real:'实际收益率',dollar:'美元',equity:'标普 500',nasdaq:'纳指',vix:'VIX',credit:'高收益利差',btc:'比特币'};
export function changeLabel(item: ProductMarketItem) { return item.change == null ? '—' : `${item.change > 0 ? '+' : ''}${item.change.toFixed(2)} ${item.change_unit}`; }
export function sessionDate(item: ProductMarketItem): string | null { return item.details.timestamp?.slice(0, 10) ?? null; }
export function isCurrent(item: ProductMarketItem, now = Date.now()): boolean {
  const at = Date.parse(item.details.timestamp ?? '');
  return item.status === 'available' && item.freshness === 'AVAILABLE' && Number.isFinite(at) && at <= now && now - at <= 4 * 86400000 && item.details.data_mode === 'observed';
}
export interface ContextPath { key: string; label: string; chain: string[]; note: string; falsifier: string; expected: Partial<Record<MarketRole, 1 | -1>>; }
/** Fixed teaching hypotheses, never generated explanations or event attribution. */
export const CONTEXT_PATHS: ContextPath[] = [
  { key:'rates', label:'利率重定价', chain:['通胀 / 政策预期上修','短端与实际利率上行','美元偏强','黄金 / 成长股承压'], note:'先检查短端和实际利率，而不是从黄金下跌反推原因。', falsifier:'收益率未上行，或美元走弱，都会削弱这条解释。', expected:{rates2:1,real:1,dollar:1,gold:-1,nasdaq:-1} },
  { key:'easing', label:'宽松预期', chain:['增长 / 通胀降温','政策路径下修','利率与美元回落','黄金 / 成长股获得支持'], note:'弱数据也可能触发衰退担忧；股票不一定跟随利率下行上涨。', falsifier:'股票下跌、信用利差扩大时，应同时检查增长担忧。', expected:{rates2:-1,real:-1,dollar:-1,gold:1,nasdaq:1} },
  { key:'risk', label:'风险规避', chain:['增长或风险担忧','股票承压','波动率与信用压力上升','避险资产表现分化'], note:'黄金可能避险上涨，也可能在流动性冲击中被卖出；不预设方向。', falsifier:'股票上涨且 VIX 回落时，广泛风险规避缺少支持。', expected:{equity:-1,nasdaq:-1,vix:1,credit:1} },
  { key:'supply', label:'能源供给冲击', chain:['供给 / 地缘风险线索','原油上行','通胀预期可能上修','利率与股票需要另行确认'], note:'这里只核对价格；当前没有新闻证据，不能确认供给或地缘事件。', falsifier:'只有油价上涨而无供给证据，也可能来自需求、美元或仓位。', expected:{oil:1} },
];
export function checkPath(path: ContextPath, markets: ProductMarketItem[], anchor: ProductMarketItem, now = Date.now()) {
  return (Object.entries(path.expected) as Array<[MarketRole, 1 | -1]>).map(([role, expected]) => {
    const item = markets.find(row => marketRole(row) === role);
    const correctUnit = !['rates2', 'rates10', 'real', 'credit'].includes(role) || item?.change_unit === 'bp';
    const comparable = !!item && correctUnit && isCurrent(item, now) && isCurrent(anchor, now) && sessionDate(item) === sessionDate(anchor) && item.details.granularity_seconds === anchor.details.granularity_seconds && item.details.granularity_seconds === 86400;
    const state = !item || item.change == null ? 'missing' : !comparable ? 'unconfirmed' : item.change === 0 ? 'flat' : Math.sign(item.change) === expected ? 'agrees' : 'opposes';
    return { role, expected, item, state };
  });
}
export function focusMarkets(items: ProductMarketItem[]) {
  const order: MarketRole[] = ['gold','rates2','rates10','dollar','nasdaq','oil','equity','vix','btc','silver','real','credit'];
  const seen = new Set<MarketRole>();
  return items.filter(item => { const role = marketRole(item); if (!role || seen.has(role)) return false; seen.add(role); return true; }).sort((a,b) => order.indexOf(marketRole(a)!) - order.indexOf(marketRole(b)!));
}
