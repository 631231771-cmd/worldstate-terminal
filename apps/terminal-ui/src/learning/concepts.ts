export interface ConceptDefinition {
  title: string;
  explanation: string;
  whyItMatters: string;
}

export const CONCEPTS = {
  growth: { title: "增长", explanation: "描述经济活动是在扩张、放缓还是收缩。", whyItMatters: "增长变化会影响企业盈利、就业、利率预期和风险偏好。" },
  inflation: { title: "通胀", explanation: "描述整体价格水平及其变化速度。", whyItMatters: "通胀会改变央行政策预期、实际利率与资产估值。" },
  liquidity: { title: "流动性", explanation: "描述金融体系中可用资金和资产负债表空间。", whyItMatters: "流动性变化会影响融资条件、美元和风险资产承受力。" },
  policy_tightness: { title: "政策约束", explanation: "描述货币政策对经济与金融条件的限制程度。", whyItMatters: "更强的政策约束通常抬高融资成本，但不是资产涨跌的唯一原因。" },
  real_yield: { title: "实际利率", explanation: "名义利率扣除通胀预期后的回报。", whyItMatters: "它是黄金、美元和长期资产估值的重要背景变量。" },
  yield_curve: { title: "收益率曲线", explanation: "不同期限国债收益率之间的结构。", whyItMatters: "曲线变化能反映政策、增长和通胀预期的重新定价。" },
  credit_spread: { title: "信用利差", explanation: "企业债收益率相对安全国债的额外补偿。", whyItMatters: "利差走阔通常表示融资压力或风险厌恶上升。" },
  vix: { title: "VIX", explanation: "由标普 500 期权推导的短期隐含波动率指标。", whyItMatters: "它描述市场对未来波动的定价，不等同于已经发生的跌幅。" },
  consensus: { title: "Consensus", explanation: "事件发布前收集的市场一致预期。", whyItMatters: "只有 T0 前保存的预期才能用于衡量数据惊喜。" },
  surprise: { title: "Surprise", explanation: "实际值相对事前预期的偏差。", whyItMatters: "市场通常交易预期差，但反应还会受仓位、修订和同期新闻影响。" },
  revision: { title: "Revision", explanation: "官方对之前公布数值的修正。", whyItMatters: "修订可能改变市场对趋势的理解，不能与本期惊喜混为一谈。" },
  reversal: { title: "Reversal", explanation: "事件后早期方向随后发生反转。", whyItMatters: "反转可能表示最初解读被后续信息、流动性或竞争性解释覆盖。" },
} satisfies Record<string, ConceptDefinition>;

export type ConceptKey = keyof typeof CONCEPTS;
