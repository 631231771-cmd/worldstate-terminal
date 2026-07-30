import { useEffect, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, Meter, Panel } from "../../components/Primitives";
import type { ReleaseSummary, ViewKey } from "../../types";

function toneForDirection(score: number | null) {
  if (score === null) return "neutral";
  return score > 0.25 ? "bad" : score < -0.25 ? "good" : "warn";
}

export function TodayWorkspace({
  releases,
  health,
  onOpen,
}: {
  releases: ReleaseSummary[];
  health: Awaited<ReturnType<typeof api.health>> | null;
  onOpen: (releaseId: string, destination?: ViewKey) => void;
}) {
  const [today, setToday] = useState<Awaited<ReturnType<typeof api.today>> | null>(null);

  useEffect(() => {
    void api.today().then(setToday).catch(() => setToday(null));
  }, []);

  const latest = today?.latest_research.length ? today.latest_research : releases.slice(0, 5);
  const strongest = [...latest].sort(
    (left, right) => Math.abs(right.surprise_score ?? 0) - Math.abs(left.surprise_score ?? 0),
  )[0];

  return (
    <div class="workspace">
      <section class="hero">
        <div>
          <div class="eyebrow">DAILY RESEARCH BRIEF · {today?.date ?? "LOCAL"}</div>
          <h1>今天，市场重新定价了什么？</h1>
          <p>
            从官方发布和事前共识出发，沿着收益率、美元、贵金属与股指的反应链，区分事实、历史关系和当前推断。
          </p>
        </div>
        <div class="hero__method">
          <span>当前方法版本</span>
          <strong>{health?.methodology_version ?? "等待服务"}</strong>
          <p>一分钟数据只判断“最早观察到”，不声称逐笔领先。</p>
        </div>
      </section>

      <div class="summary-grid">
        <Panel title="今日待办" eyebrow="CALENDAR">
          <div class="big-number">{today?.scheduled_releases.length ?? 0}</div>
          <p class="muted">
            {today?.scheduled_releases.length
              ? "今日有已登记的宏观发布。"
              : "当前没有已登记的今日事件，以下展示最近完成的研究。"}
          </p>
        </Panel>
        <Panel title="最近研究" eyebrow="COMPLETED">
          <div class="big-number">{latest.length}</div>
          <p class="muted">已完成结构化事实、跨资产窗口、历史匹配和解释。</p>
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
        title="最近发生的宏观发布"
        eyebrow="RELEASE → REACTION → EXPLANATION"
        aside={<span class="muted">点击进入完整复盘</span>}
      >
        <div class="research-feed">
          {latest.map((release) => (
            <button
              type="button"
              class="research-row"
              key={release.id}
              onClick={() => onOpen(release.id)}
            >
              <time>
                {new Intl.DateTimeFormat("zh-CN", {
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Shanghai",
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
                <Badge tone={toneForDirection(release.surprise_score)}>
                  惊喜 {release.surprise_score?.toFixed(2) ?? "—"}
                </Badge>
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
            <li><span>02</span><div><strong>再看最早反应</strong><p>短端利率、美元、黄金和股指是否互相确认。</p></div></li>
            <li><span>03</span><div><strong>分阶段检查</strong><p>初始冲击有没有在发布会或问答阶段反转。</p></div></li>
            <li><span>04</span><div><strong>最后看解释</strong><p>比较候选传导链、竞争解释与能推翻它们的证据。</p></div></li>
          </ol>
        </Panel>
        <Panel title="诚实边界" eyebrow="WHAT WE DO NOT CLAIM">
          <ul class="boundary-list">
            <li>不把“有人买入/卖出”当成最终宏观解释。</li>
            <li>不把 ZN 期货价格变化伪装成精确的十年期现金收益率变化。</li>
            <li>fixture 只用于演示完整链路，不冒充交易所历史行情。</li>
            <li>样本少于 15 个时，不输出概率与百分位推断。</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
