# Agent Reach / X 本地只读接入

World State Terminal 可以使用用户已经配置好的 Agent Reach Twitter Cookie，
读取一组有限、可审计的宏观账号时间线。该接入用于补充实时观点，不替代事实源、
宏观数据或跨资产价格验证。

## 安全边界

- Cookie 只保存在用户目录下的 Agent Reach 配置文件中。
- Macro Engine 只在启动 `twitter user-posts` 子进程时读取两个必要字段。
- 凭据只通过该子进程环境传递，不会成为命令行参数。
- 标准错误被丢弃；接口只返回安全的成功、超时、上游错误或格式错误状态。
- HTTP 响应、前端、应用日志、数据库和 Git 均不接触 Cookie 值。
- X 推文始终标注为“实时观点”，不能作为已经证实的市场原因。

## 默认研究池

默认按六个来源分别调用，每个来源最多四条：

| 来源 | 分类 | 研究角色 |
|---|---|---|
| Federal Reserve | official | 美国货币政策与数据 |
| ECB | official | 欧洲利率、通胀与金融条件 |
| IMF News | institutional | 全球增长与政策框架 |
| Liz Ann Sonders | researcher | 经济数据与市场内部结构 |
| Mohamed El-Erian | practitioner | 宏观政策与市场定价 |
| Joe Weisenthal | practitioner | 市场叙事与实时线索 |

调用最多两路并发，默认复用二十分钟缓存。某个账号失败不会阻断其他账号，也不会
阻断新闻、行情、宏观数据或 AI 导师。

## 本地配置

桌面启动器默认加入以下非敏感设置：

```text
MACRO_AGENT_REACH_X_ENABLED=true
MACRO_AGENT_REACH_X_POSTS_PER_ACCOUNT=4
MACRO_AGENT_REACH_X_CACHE_SECONDS=1200
```

高级用户可以使用：

```text
MACRO_AGENT_REACH_CONFIG_PATH=C:\Users\<user>\.agent-reach\config.yaml
MACRO_TWITTER_CLI_PATH=C:\Users\<user>\.local\bin\twitter.exe
MACRO_AGENT_REACH_X_TIMEOUT_SECONDS=14
```

不要把 Cookie 写进这些设置，也不要把 `TWITTER_AUTH_TOKEN` 或 `TWITTER_CT0`
提交到仓库。

## 页面中的可观测性

“观点与调用”工作区显示：

- 已配置、已连接和可执行文件状态；
- 本轮计划调用、成功调用和公开条目数；
- 新调用或缓存命中；
- 每个账号的研究角色、成功状态、耗时与最新内容时间；
- 官方 X API、ClawFeed 和 WebMCP 的独立状态。

这样可以区分“没有观点”“来源调用失败”和“仍在使用缓存”，而不是把所有情况
都显示成一个模糊的在线标识。
