# GPT-6-Sol 任务：定位 ATAS GC 本机桥断点

日期：2026-09-24。用户要求将接下来的诊断交给 GPT-6-Sol；本文件是可直接复用的任务提示词。

## 本次执行结果与下一步

GPT-6-Sol已实际加载诊断版并找到断点。05:54:42 UTC日志显示
`initialized`、`contract: rejected info=GC legacy=GC provider=present`，
05:54:52收到真实`Trade`回调。指标在合约guard处停止，尚未创建WebSocket。
加载失败和接收端故障均不能解释这个已观测到的断点。

公开SDK的IInstrumentInfo、IChart、MarketDataArg未提供可用于此图的额外月份字段。
下一次优先用现有连接打开独立的、明确月份的GCZ6合约图，保留原连续图，
通过诊断日志验证SDK实际返回的身份，再测试报价。不要硬编码标题上的月份。
本轮尝试进入合约选择时，主窗口捕获连续失败，未更改图表或连接。

当前诊断版构建0警告0错误，接收端5项测试通过。最后读取仍为
`enabled=true, connected=false, quote=null`；尚无真实报价验收。
下面保留最初任务框架，所有“尚未导入”的描述指交接时状态；目前诊断版已加载。

## 目标与范围

在 `F:\Code\world\worldstate-terminal`、`feature/v0.7-terminal-rebuild`
继续现有 GC 只读 PoC。基线为 `a379828a4`。找到指标启用后没有连接的真实断点，
根据证据做最小修复，并让当前 GC 图表报价进入 WorldState 工作台。
完成 GC 验证后停止，不扩其他资产或研究功能。

先读 `AGENTS.md`、`docs/data/atas-local-bridge-poc.md`、
`project-memory/CURRENT.md` 顶部；不需要重读全部产品迁移历史。

## 已确认事实

1. 用户已经授权导入本项目 DLL、启用 GC 本机桥、短时只读核对。
2. ATAS 当前图表为 `#GCZ6@COMEX`。Rithmic 连接有新行情更新。
   先前把其他连接的 `Delayed 15m` 标签当作本图表延迟是错误判断，已撤回。
3. 修正版 DLL 曾被导入；指标管理中 `Added (1)`、启用勾选和 Apply 均已观察。
   这不等于确认了当前实例成功执行。
4. API health 正常。真实 `.NET ClientWebSocket` 空连接成功，连接期间
   `/v2/product/live-gc` 返回 `connected=true`；已正常关闭，未发送假报价。
   因而接收端可工作，重点检查指标加载、初始化、合约 guard 和发送线程。
5. ATAS 自身仍未建立连接：最新核对是 `enabled=true, connected=false,
   last_seen_at=null, quote=null`。后续必须重新读取，不能把此快照当永恒状态。
6. ATAS 13:08/13:16 有旧的程序集解析警告，13:32有 Changed library。
   旧警告不能证明13:32之后的实例也失败。

## 当前诊断准备

`WorldStateBridge.cs` 已增加 `diag-v1` 有界本机诊断，已编译，交接时尚未导入。
日志位于 `%LOCALAPPDATA%\WorldStateTerminal\logs\atas-gc-bridge.log`，
记录实例ID、启用、初始化、SDK合约字符串、socket阶段、首个交易回调和发送状态。
不记录账户、凭据、价格历史，文件上限128KiB。

构建：

```powershell
.runtime\dotnet-sdk\dotnet.exe build apps/atas-local-bridge/WorldStateBridge.csproj --no-restore
```

输出：`apps\atas-local-bridge\bin\Debug\net10.0-windows\WorldStateBridge.dll`。
ATAS 安装目录：`E:\ATAS Platform`。
已导入副本：`%APPDATA%\ATAS\Indicators\WorldStateBridge.dll`。
ATAS 日志：`%APPDATA%\ATAS\Logs\app_20260924*.log`，只筛选桥接相关内容。

## 执行顺序

### 1. 确认实际执行的版本

一次受控加载诊断版，用日志中的 `diag-v1` 和实例ID确认执行。
DLL文件哈希一致只能证明文件复制成功，不能证明运行中的实例已替换。
避免在未确认实例状态时反复导入或要求用户反复重启。

### 2. 定位断点

- 没有诊断记录：检查实际加载/实例化/日志写入条件。
- 有 enabled/init，contract rejected：检查SDK返回的真实值。
  `InstrumentInfo.Instrument` 和旧 `Instrument` 可能不是图表标题上的具体合约。
- contract accepted但未connected：检查发送线程和socket错误。
- connected但无quote：检查真实trade回调、时间语义、快照校验和server关闭原因。

保持严格合约校验；不能硬编码GCZ6、把裸GC猜成某月份，或重标旧时间戳。

### 3. 最小修复和回归

只修改断点涉及的桥接代码。保留 opt-in、127.0.0.1、只读、GC范围、
真实合约和时间语义。对具体错误增加回归，构建并核对修复版实例确实加载。
后端现有回归：`services/research-api/tests/test_atas_local_bridge.py`。

### 4. 实际验收

必须取得当前ATAS数据，核对：连接、合约、价格、事件时间、接收时间、bid/ask、
1m OHLCV。短时核对断开/重连、CPU和ATAS稳定性。
若只通了socket，不能声称行情已通；若没有报价，准确记录仍缺哪段证据。

## 必须遵守

- 不操作Rithmic登录、不创建第二会话、不改现有连接。
- 不使用PatchTool，不修改ATAS官方程序集，不抓进程内存。
- 不读取DOM、Footprint、MBO或历史tick，不下单。
- 不写MarketDataManifest、AnalysisRun或事件研究表；仅临时UI报价。
- 保留现有runtime DB，不导入fixture测试实际页面。
- ATAS UI用computer-use skill；若窗口捕获/输入几何错误，停止猜坐标。
  独立Indicators窗口此前可操作，主窗口捕获曾不可靠。
- 保留工作树内已有诊断改动；不要重写整个桥接框架或工作台。

## 交付

报告真实根因与证据、最小改动、测试、当前运行状态和未完成验证。
若仍阻塞，明确哪个观察/工具能力缺失，以及下一步如何获得它。
不要以“编译通过”或“DLL已导入”代替端到端验收。
