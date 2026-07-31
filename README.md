# WorldState Terminal

WorldState Terminal（世界状态终端）是一个个人使用、local-first 的宏观研究与交易辅助终端。它围绕一个问题组织所有数据与页面：

> 宏观事件公布后，市场为什么这样定价？

它不是 World Monitor 的延伸，也不是新闻墙、世界地图或自动交易系统。当前主线是美国 CPI、非农和 FOMC 事件，结合 point-in-time 发布值、共识快照、跨资产事件窗口、历史匹配与受证据约束的解释。

## 现在可以做什么

- 查看 CPI、非农、FOMC 发布及其指标集合和阶段。
- 保存 Actual、Consensus、Previous、Revision 与来源快照。
- 分析黄金、白银、美元、ES/NQ、2Y/10Y 等事件前后窗口。
- 识别最早观察到的显著反应、冲高回落、方向反转和 FOMC 分阶段变化。
- 用固定匹配规则对比历史事件，并按样本量决定统计、案例或不推断。
- 生成区分事实、历史关系、主假设、竞争解释和数据缺口的复盘报告。
- 在没有外部密钥时使用可追溯 fixture 完成端到端演示。

## 一键打开（Windows）

日常使用只推荐双击桌面的 `WorldState Terminal.bat`。它会定位当前仓库并委托给仓库根目录的
`WorldStateApp.bat`；仓库脚本优先启动可用的 Tauri 构建，否则使用经过验证的 BAT
启动链。首次使用 BAT 启动链时会准备 Python 与前端依赖、迁移数据库，然后打开：

- 终端：<http://127.0.0.1:4173/#today>
- API 文档：<http://127.0.0.1:8000/docs>

在仓库内一键打开时使用：

```powershell
.\WorldStateApp.bat
```

维护和诊断只使用：

```powershell
.\WorldState.bat start
.\WorldState.bat status
.\WorldState.bat stop
.\WorldState.bat doctor
```

需要 Python 3.12 与 Node.js 20+。桌面壳的编译说明见
[`docs/desktop/windows.md`](docs/desktop/windows.md)。

## 仓库结构

```text
apps/
  terminal-ui/       五个研究工作区
  desktop-tauri/     Windows 桌面壳
services/
  research-api/      FastAPI、领域模型、事件与研究引擎
data/
  fixtures/          可追溯演示数据
  macro/             宏观目录和规则输入
docs/                架构、方法、数据与迁移说明
research/            迁移校验与研究产物
project-memory/      可作为 Obsidian vault 的项目记忆
```

## 数据库与演示

```powershell
.\WorldState.bat migrate
.\WorldState.bat bootstrap
```

数据库 v3 会保留并回填旧 CPI 实验室中仍有价值的数据，再删除语义重复的旧事件表。迁移前本地备份保存在 `.runtime/backups/`（该目录不会提交）。

内置 CPI、非农与 FOMC 数据均标为 fixture；它们用于验证流程，不会伪装成实时或官方抓取数据。真实分钟行情第一版通过 CSV 导入；FRED/ALFRED、OpenBB 和其他行情源均位于可替换 provider 边界。

## 开发与验证

```powershell
$env:PYTHONPATH="$PWD\services\research-api\src"
services\research-api\.venv\Scripts\python.exe -m ruff check services\research-api
services\research-api\.venv\Scripts\python.exe -m mypy services\research-api\src services\research-api\tests
services\research-api\.venv\Scripts\python.exe -m pytest services\research-api\tests
npm run build --prefix apps\terminal-ui
```

## 研究边界

- 惊喜值和窗口反应是计算事实；解释是带置信度的竞争性假设。
- 分钟数据只能判断“最早观察到”，不能证明机构订单或关键词交易的真实先后。
- 事件污染会降低解释置信度并限制因果措辞。
- 代理、fixture、人工录入、延迟和缺失都会显式标注。
- AI 只能读取结构化 EvidencePack，不能补写系统没有取得的事实。

详细方法见 [`docs/macro/methodology.md`](docs/macro/methodology.md)，完整迁移报告见
[`docs/migration/final-report.md`](docs/migration/final-report.md)。

## 许可证

本项目以 AGPL-3.0-or-later 发布。第三方采用与许可证边界见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
