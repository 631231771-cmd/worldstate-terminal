import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Meter, Panel } from "../../components/Primitives";
import type { ReleaseSummary, ViewKey } from "../../types";

function toneForDirection(score: number | null) {
  if (score === null) return "neutral" as const;
  return score > 0.25 ? ("bad" as const) : score < -0.25 ? ("good" as const) : ("warn" as const);
}

export function TodayWorkspace({
  releases: _releases,
  health,
  onOpen,
}: {
  releases: ReleaseSummary[];
  health: Awaited<ReturnType<typeof api.health>> | null;
  onOpen: (releaseId: string, destination?: ViewKey) => void;
}) {
  const [today, setToday] = useState<Awaited<ReturnType<typeof api.today>> | null>(null);
  const [brief, setBrief] = useState<Awaited<ReturnType<typeof api.dailyBrief>> | null>(null);

  useEffect(() => {
    void Promise.all([api.today(), api.dailyBrief()])
      .then(([todayResult, briefResult]) => {
        setToday(todayResult);
        setBrief(briefResult);
      })
      .catch(() => {
        setToday(null);
        setBrief(null);
      });
  }, []);

  // The API deliberately returns only released, completed and reproducible
  // research. Never substitute a recent release row here: that made future,
  // pending and fixture records look like completed research.
  const latest = today?.latest_research ?? [];
  const strongest = [...latest].sort(
    (left, right) => Math.abs(right.surprise_score ?? 0) - Math.abs(left.surprise_score ?? 0),
  )[0];

  return (
    <div class="workspace">
      <section class="hero">
        <div>
          <div class="eyebrow">DAILY RESEARCH BRIEF · {today?.date ?? "LOCAL"}</div>
          <h1>今天，市场重新定价了什么？</h1>
          <p>Today 只呈现已发布、已完成分析且保留可复现输入的研究，不把日历或演示数据伪装成结论。</p>
        </div>
        <div class="hero__method">
          <span>当前方法版本</span>
          <strong>{health?.methodology_version ?? "等待服务"}</strong>
          <p>分钟数据只判断“最早观察到”，不声称逐笔领先。</p>
        </div>
      </section>

      <Panel title="当前宏观状态" eyebrow="WORLD STATE" aside={<span class="muted">{brief?.world_state.regime.label ?? "等待数据"}</span>}>
        <div class="state-strip">
          {Object.entries(brief?.world_state.dimensions ?? {}).slice(0, 6).map(([key, dimension]) => (
            <div class="state-strip__item" key={key}>
              <span>{key.replace("_", " ")}</span>
              <strong class={dimension.score !== null && dimension.score >= 0 ? "positive" : "negative"}>
                {dimension.score === null ? "—" : dimension.score.toFixed(2)}
              </strong>
              <small>{dimension.direction} · 覆盖 {Math.round(dimension.coverage * 100)}%</small>
            </div>
          ))}
        </div>
        <p class="method-note">状态分数是结构化序列的变化线索，不是“好/坏”评级；鼠标悬停或进入 World State 可查看驱动与缺口。</p>
      </Panel>

      <div class="two-column">
        <Panel title="最近最重要的变化" eyebrow="TOP CHANGES">
          <div class="change-list">
            {(brief?.biggest_changes ?? []).slice(0, 5).map((change) => (
              <div class="change-list__row" key={`${change.category}-${change.what_changed}`}>
                <span class="change-list__dot" />
                <div><strong>{change.what_changed}</strong><p>{change.why_it_matters}</p></div>
                <Badge tone={change.confidence >= 0.65 ? "good" : "warn"}>{Math.round(change.confidence * 100)}%</Badge>
              </div>
            ))}
            {!brief?.biggest_changes.length ? <div class="state-message"><div><h2>暂无可排序的变化</h2><p>当前 data_mode 没有足够的结构化观测。</p></div></div> : null}
          </div>
        </Panel>
        <Panel title="市场确认" eyebrow="RATES · USD · RISK">
          <div class="market-confirmation">
            {(brief?.market_confirmation ?? []).slice(0, 6).map((market) => (
              <div class="market-confirmation__row" key={String(market.instrument_key)}>
                <span>{String(market.title)}</span>
                <strong class={Number(market.change_percent ?? 0) >= 0 ? "positive" : "negative"}>
                  {market.change_percent == null ? "—" : `${Number(market.change_percent).toFixed(2)}%`}
                </strong>
              </div>
            ))}
            {!brief?.market_confirmation.length ? <p class="muted">当前没有满足模式和时段条件的市场数据。</p> : null}
          </div>
        </Panel>
      </div>

      <div class="summary-grid">
        <Panel title="今日待办" eyebrow="CALENDAR">
          <div class="big-number">{today?.scheduled_releases.length ?? 0}</div>
          <p class="muted">
            {today?.scheduled_releases.length ? "今日有已登记的宏观发布。" : "当前没有已登记的今日事件。"}
          </p>
        </Panel>
        <Panel title="最近研究" eyebrow="COMPLETED">
          <div class="big-number">{latest.length}</div>
          <p class="muted">
            {latest.length ? "已发布且可复现的结构化研究。" : "暂无已完成真实研究。当前数据模式没有满足完整性条件的记录。"}
          </p>
        </Panel>
        <Panel title="最强预期差" eyebrow="SURPRISE">
          <strong class="summary-callout">{strongest?.classification ?? "数据不足"}</strong>
          <p class="muted">{strongest ? `${strongest.title} · ${strongest.period_label}` : "—"}</p>
        </Panel>
        <Panel title="系统状态" eyebrow="DATA HEALTH">
          <strong class="summary-callout">{health?.database.status === "ok" ? "可研究" : "降级"}</strong>
          <p class="muted">AI：{health?.ai_provider === "none" ? "模板报告模式" : health?.ai_provider}</p>
        </Panel>
      </div>

      <Panel
        title="最近已完成的宏观研究"
        eyebrow="RELEASE → REACTION → EXPLANATION"
        aside={<span class="muted">点击进入完整复盘</span>}
      >
        <div class="research-feed">
          {latest.length === 0 ? (
            <div class="state-message">
              <div class="state-message__mark">—</div>
              <div>
                <h2>暂无已完成真实研究</h2>
                <p>未来事件、待分析事件、Fixture 和不可复现运行不会显示在这里。</p>
              </div>
            </div>
          ) : latest.map((release) => (
            <button type="button" class="research-row" key={release.id} onClick={() => onOpen(release.id)}>
              <time>
                {new Intl.DateTimeFormat("zh-CN", {
                  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai",
                }).format(new Date(release.released_at ?? release.scheduled_at))}
              </time>
              <div class="research-row__main">
                <span class="row-meta">{release.release_type} · {release.period_label}</span>
                <strong>{release.title}</strong>
                <p>{release.classification ?? "尚未形成综合分类"}</p>
              </div>
              <div class="research-row__confidence">
                <span>解释置信度 {Math.round((release.confidence ?? 0) * 100)}%</span>
                <Meter value={release.confidence ?? 0} />
              </div>
              <div class="research-row__flags">
                <Badge tone={toneForDirection(release.surprise_score)}>惊喜 {release.surprise_score?.toFixed(2) ?? "—"}</Badge>
                {release.data_mode === "fixture" ? <Badge tone="warn">FIXTURE</Badge> : null}
                {!release.clean_window ? <Badge tone="bad">窗口受污染</Badge> : null}
              </div>
              <span class="row-arrow">→</span>
            </button>
          ))}
        </div>
      </Panel>

      <div class="two-column">
        <Panel title="如何阅读一场事件" eyebrow="LEARNING PATH">
          <ol class="learning-chain">
            <li><span>01</span><div><strong>先看预期差</strong><p>Actual、Consensus、Previous 与修订分别说了什么。</p></div></li>
            <li><span>02</span><div><strong>再看最早反应</strong><p>收益率、美元、黄金和股指是否相互确认。</p></div></li>
            <li><span>03</span><div><strong>分阶段检查</strong><p>初始冲击是否在发布会或问答阶段反转。</p></div></li>
            <li><span>04</span><div><strong>最后看解释</strong><p>比较候选传导链、竞争性解释与证据边界。</p></div></li>
          </ol>
        </Panel>
        <Panel title="诚实边界" eyebrow="WHAT WE DO NOT CLAIM">
          <ul class="boundary-list">
            <li>不把买卖行为本身当成最终宏观原因。</li>
            <li>不把代理资产价格伪装成原始资产。</li>
            <li>Fixture 只用于演示完整链路，不冒充交易所历史行情。</li>
            <li>样本不足时不输出概率和百分位推断。</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
