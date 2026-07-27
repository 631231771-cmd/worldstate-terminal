# Phase 7 产品与开源案例研究

本轮从
[X-Plore 中文仓库索引](https://github.com/lvy010/X-Plore/blob/main/repo/github_repos_cn.md)
中筛选与 World State Terminal 当前问题直接相关的项目。采用的是产品原则和
信息架构；本轮没有复制第三方实现代码，也没有引入大型运行时依赖。

## 采用结论

| 项目 | 成熟做法 | 本项目采用 | 明确不采用 | 许可 |
|---|---|---|---|---|
| [BettaFish](https://github.com/666ghj/BettaFish) | 多源舆情、破除信息茧房、观点冲突 | 观点按机构、研究者、实践者、X 分桶轮选；每条观点必须翻译成验证变量和限制 | 不引入完整多智能体爬虫；不复制 GPLv2 代码 | GPLv2 |
| [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | 结构化报告、数据源失败降级、时效与完整性 | X 单源失败不阻断；页面显示证据来源、状态与研究边界 | 不引入买卖点、止损止盈和交易信号 | MIT |
| [Hermes HUD UI](https://github.com/joeynyc/hermes-hudui) | 健康、会话、成本和调用成为独立页面 | 新增“观点与调用”工作区和逐来源调用账本 | 不读取其他 Agent 私人记忆，不照搬 13 个标签页 | MIT |
| [Lumina Note](https://github.com/blueberrycongee/Lumina-Note) | 本地优先、多视图知识工作区、用户控制 AI 上下文 | 总览、事件、市场、观点、学习五个真实 URL 视图；Cookie 留在本机 | 暂不复制编辑器、知识图谱、插件系统 | Apache-2.0 |
| [Tab Out](https://github.com/zarazhangrui/tab-out) | 分组、去重、快速切换、本地保存 | 研究对象选择器与紧凑分组导航 | 不做浏览器扩展，不读取用户标签页 | MIT |
| [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) | 按能力、成本、安全和隐私做模型路由 | 保留 OpenAI、兼容服务、Ollama、规则回退的显式边界 | 当前规模不引入系统级推理路由器 | Apache-2.0 |

## 信息架构变化

旧版是一条很长的单页：

```text
首页 → 不断向下滚动所有内容
```

新版是一个研究工作区：

```text
今日总览
├── 事件研究：事件选择 → 事实 → 预期差 → 传导链 → 验证与反证
├── 市场实验室：市场选择 → 宏观角色 → 当日解释 → 已知 / 未知
├── 观点与调用：连接状态 → 调用账本 → 观点假设 → 来源地图
└── 学习与来源：今日概念 → 可选课程 → 长期数据 → 方法来源
```

每个工作区使用 `?view=` URL，浏览器前进和后退可正常工作。事件和市场进一步
使用 `event` 与 `market` 参数保存当前研究对象。

## 内容选择规则

1. 首页仍保持有限：一条主线、五段深读、有限事件和有限市场。
2. 深层页面可以更丰富，但必须区分事实、解释、验证和未知。
3. 观点按来源类别轮选，单一来源最多两条，避免一种叙事占满页面。
4. 社交内容只作为线索；即使互动量很高，也不会自动升级为事实。
5. 私人订单流不可见时明确写“未知”，不把价格波动伪装成已证实的机构行为。
