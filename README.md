# WorldState Terminal

WorldState Terminal（世界状态终端）是一款个人使用、local-first 的宏观研究与交易辅助终端。它围绕一个问题组织数据与页面：

> 宏观事件公布后，市场为什么这样定价？

它不是新闻墙、世界地图、自动交易系统，也不把相关性写成唯一因果。当前研究主线固定为美国 CPI、非农和 FOMC，并结合 point-in-time 发布值、发布前共识、跨资产事件窗口、历史匹配和受证据约束的解释。

## v0.7 当前状态

当前开发分支 `feature/v0.7-live-global` 在 v0.6 operational macro 基础上
启用了官方公共宏观数据、数据新鲜度与全球比较的第一条真实链路。产品版本
为 `0.7.0`，数据库迁移头为 `0009_operational_state`。

- **已验证的公共来源**：ECB Data Portal 的 EUR/USD 与欧元区 HICP，以及
  Bank of England IADB 的 Bank Rate。它们写入 `observed`，保留来源工件、
  抓取时间、质量记录和明确的非 PIT 限制。
- **新增控制面**：数据控制中心、`/v2/data/sync/public`、
  `/v2/data/bootstrap-free`、`/v2/data/freshness`、`/v2/macro-systems`、
  World State 历史快照和 Watchlist。
- **诚实降级**：ECB 单个序列无数据时只返回 `partial` 并保留成功序列；
  FRED/ALFRED、Trading Economics、Databento、BOJ 和中国官方出口仍按
  密钥、权限或目录配置显示 `not_configured`。绝不用 fixture 填补 observed。
- **全球宏观边界**：US、China、EA19、Japan、UK 的比较只使用已有
  `Series/Observation`，缺口、覆盖率和系统组件状态会直接显示；这不是完整
  全球数据终端，也不是因果预测器。

详细证据与限制见 [`docs/macro/v0.7-live-global.md`](docs/macro/v0.7-live-global.md)。

## v0.6 历史状态

当前开发分支 `feature/v0.6-operational-intelligence` 在 v0.5.1 truthfulness
基础上增加了可每日使用的 World State、Daily Macro Brief、跨资产市场页、
Series Explorer、Thesis Book、结构化上下文助手和全球宏观第一层。它们都
复用既有 point-in-time/observed-fixture 数据边界；没有数据时显示缺口，
不会把 fixture 当成 live。

- **可在本机使用**：Today（World State、Top Changes、Market Confirmation、Upcoming）、
  World State、Markets、Series、Research/Thesis、Releases、Event Lab、Cross Asset、
  Data & Methods，以及 `/v2/world-state`、`/v2/daily-brief`、`/v2/market-dashboard`、
  `/v2/series`、`/v2/theses`、`/v2/global-macro`。
- **真实数据就绪但依赖配置**：FRED/ALFRED、Trading Economics、Databento；BLS/Fed
  按官方来源工作。没有密钥/权限时 API 会返回 `not_configured` 或 `unavailable`。
- **Fixture 作用**：干净 demo 数据只用于确认页面和确定性方法链，provider 和
  `data_mode` 都单独标记。真实 observed 覆盖仍需按 v0.5 数据源边界导入。
- **发布边界**：Tauri/Windows 入口保持可用，但没有冻结 Python sidecar 或签名
  安装包；空白电脑仍需 Python 3.12、Node.js 20+ 等本机依赖。

详细方法见 [`docs/macro/v0.6-operational-intelligence.md`](docs/macro/v0.6-operational-intelligence.md)。

## v0.5 历史状态

v0.5 Data Foundation 正在 PR #8 的 Draft 分支上实施和稳定化，尚未合并到 `main`。当前状态必须按以下层级理解：

- **已实现**：v0.5 Provider 统一契约；BLS、Federal Reserve、FRED/ALFRED、Trading Economics、Databento 的持久化编排；`observed` / `fixture` 数据隔离；Provider 运行、权限、配额、原始工件、同步任务、市场数据清单、对账记录和回填任务；非阻塞本地调度器与可恢复回填 worker；Provider/覆盖率/同步/回填 API 和现有终端中的数据溯源展示。
- **fixture 已测试**：内置 CPI、非农和 FOMC 研究切片，以及 Provider 响应适配、成本闸门、调度状态机和对账服务的测试样例。fixture 只证明流程可运行，不代表真实数据就绪。
- **可接真实数据（observed-ready）**：BLS 公共档和 Federal Reserve 公开网页无需密钥；FOMC 支持 2015–2020 官方历史页以及当前/未来会议日历；FRED/ALFRED、Trading Economics 和 Databento 有明确的凭据、PIT、成本和许可边界；CSV 与手工录入仍可用于合法获得的数据。
- **尚未完成**：本轮无密钥环境没有形成完整 observed 历史。FRED/ALFRED 因缺少 FRED key 被阻塞；TE 当前抓取因缺少 key 被阻塞，历史回放还需要 PIT entitlement；Databento 因缺少 key/数据权限且付费开关默认关闭而被阻塞。BLS 公共模式不需要 key，但本验证网络访问其 schedule HTML 时收到 HTTP 403，且当前 API 不能重建旧的首次公布值；Federal Reserve 公共页已可验证。公开可访问不等于已完成全量回填。
- **发布打包未就绪**：Tauri 开发构建仍依赖本机 Python 3.12；当前没有冻结 Python sidecar，也没有签名安装包，不能把单独 EXE 当作可在空白电脑独立运行的发布版本。

最终测试、迁移和 GitHub CI 结果以 [`docs/stabilization/v0.5-data-foundation-report.md`](docs/stabilization/v0.5-data-foundation-report.md) 的验证记录为准；验证完成前不应将 PR #8 标记为 Ready 或合并。

## 日常打开

Windows 日常使用入口：

```powershell
.\WorldStateApp.bat
```

桌面快捷入口会委托给仓库内的启动器。开发/BAT 路径需要 Python 3.12 和 Node.js 20+。常用维护命令：

```powershell
.\WorldState.bat start
.\WorldState.bat status
.\WorldState.bat stop
.\WorldState.bat doctor
```

启动后可访问：

- Terminal UI：<http://127.0.0.1:4173/#today>
- Research API：<http://127.0.0.1:8000/docs>

桌面边界和构建说明见 [`docs/desktop/windows.md`](docs/desktop/windows.md)。

## 数据基础命令

先迁移数据库：

```powershell
.\WorldState.bat migrate
```

诊断和只读状态：

```powershell
.\WorldState.bat data-doctor
.\WorldState.bat data-status
.\WorldState.bat estimate-backfill
```

`estimate-backfill` 返回本地记录量/体量/成本估算，不是 Databento 的实时账单报价，也不是下载许可。`backfill` 会持久化经服务端重新估算的任务；本地 worker 在调度开启时领取任务，并按 official → consensus → market → analysis 顺序执行。任何实际付费切片都必须重新取得 Databento 的新鲜高置信报价，并同时通过显式开关、单次与累计预算、凭据和数据权限；fallback 估算永远不能授权下载。失败或部分完成会保留进度、manifest 和明确 blocker。

以下命令已连接持久化编排。它们会返回 `completed`、`partial` 或 `blocked`，不会因上游缺失而偷偷回退到 fixture：

```powershell
.\WorldState.bat sync-official
.\WorldState.bat sync-calendar
.\WorldState.bat snapshot-consensus
.\WorldState.bat sync-market
.\WorldState.bat reconcile-data
```

如需内置 fixture 演示，必须显式执行：

```powershell
.\WorldState.bat bootstrap
```

默认 `WORLDSTATE_DEMO_MODE=false`，因此正常启动不会把 fixture 当成 observed 数据自动注入。

## 数据源边界

| 来源 | 当前能力 | 现实限制 |
| --- | --- | --- |
| BLS | CPI/就业系列与官方发布时间适配器；无 key 时可使用受限公共档 | 当前 BLS API 是当前/修订后序列接口，不是完整历史 vintage 档案；不能据此重建过去首次公布值 |
| Federal Reserve | 2015–2020 官方历史档案、当前/未来 FOMC 日历与 statement/press conference 等官方材料 | 未来会议会先保存 scheduled stage；`key_qa` / `press_end` 没有可验证时间时保持缺失，绝不按固定时长伪造 |
| FRED/ALFRED | 观测、vintage 与 point-in-time 适配器 | 必须配置 FRED API key；本轮环境未配置 |
| Trading Economics | 调查共识快照、官方值交叉核验与 PIT 历史回放 | 按时的 T-24h/T-1h/T-5m/T+5m 使用当前抓取；只有错过后的回放使用 PIT。配置健康检查不发日历请求、不消耗隐藏配额；真实同步成功才是在线健康证据 |
| Databento | 期货合约解析、成本估算、事件关联 OHLCV/manifest 与完整性核验 | 依赖 API key、数据权限和交易所许可；付费下载必须同时通过显式开关与预算上限；长期窗口仍是实验性边界 |

Trading Economics 与 Databento 原始响应只用于本地可追溯研究，不随仓库或 API 对外分发。

资产语义不会被隐藏：DX、VX 是期货，不是现金 DXY/VIX；ZT、ZN 是美国国债期货价格代理，不是 2 年/10 年现金收益率的精确基点变化。每日现金收益率可以由 FRED 系列独立展示，但不得与期货代理混写。

更完整说明：

- [`docs/data/providers.md`](docs/data/providers.md)
- [`docs/data/quality.md`](docs/data/quality.md)
- [`docs/data/backfill-cost-control.md`](docs/data/backfill-cost-control.md)
- [`docs/macro/methodology.md`](docs/macro/methodology.md)

覆盖率中的“已保存”与“可用于分析”不是同一个概念。`stored_not_eligible`
表示数据库中有记录，但它可能是修订后 actual、T0 后共识，或尚未通过质量/
完整性对账的 market manifest；只有 `analysis_ready` 才能进入默认研究选择。

## 仓库结构

```text
apps/
  terminal-ui/       宏观研究终端界面
  desktop-tauri/     Windows 桌面壳
services/
  research-api/      FastAPI、领域模型、事件与研究引擎、Provider 适配器
data/
  fixtures/          可追溯演示数据（绝不伪装成 live/observed）
  macro/             指标、资产、规则和研究目录
docs/                架构、方法、数据与稳定化说明
research/            研究/迁移校验产物
project-memory/      可作为 Obsidian vault 的项目记忆
```

## 开发验证

```powershell
$env:PYTHONPATH="$PWD\services\research-api\src"
services\research-api\.venv\Scripts\python.exe -m ruff check services\research-api
services\research-api\.venv\Scripts\python.exe -m mypy services\research-api\src services\research-api\tests
services\research-api\.venv\Scripts\python.exe -m pytest services\research-api\tests
npm run build --prefix apps\terminal-ui
```

当前 v0.5.1 稳定化的测试结果以最新本地验证和 GitHub Actions 为准；不再把历史测试数量或旧 SHA 当作当前发布证明。惊喜、窗口、
历史匹配、Evidence、Regime 和交易时段等关键研究逻辑的 CI 门槛集合为
**96%**。不要用旧的 v0.4 测试数字代表当前工作区。

## 研究边界

- 只有至少 20 个严格早于 T0 的历史预测误差样本且方差非零时，才输出真正的 `surprise_z`；阈值缩放使用独立字段。
- 分钟数据只能判断“在当前粒度下最早观察到的显著反应”，不能证明订单流或交易者行为的真实先后。
- 污染事件、低覆盖率、代理资产、粗粒度、fixture、人工录入和延迟都会显式降低或限制结论。
- 长窗口使用实验性的 `exchange-session-lite`，它不等于完整、获许可的交易所日历，也不覆盖所有结算、临时休市和换月规则。
- AI 只能总结结构化 EvidencePack；每条事实/推断绑定证据 ID，不能补写系统没有取得的数据，也不能输出唯一确定因果。

## 许可证

项目以 AGPL-3.0-or-later 发布。第三方采用与许可边界见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。第三方数据的访问权不等于再分发权。
