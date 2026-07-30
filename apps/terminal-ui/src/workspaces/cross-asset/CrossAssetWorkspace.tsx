import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../../api/client";
import { CrossAssetChart } from "../../components/CrossAssetChart";
import { Badge, Panel, StateMessage } from "../../components/Primitives";
import type { ReleaseSummary, TimelineResponse, WindowsResponse } from "../../types";

const CORE_KEYS = ["gold_gc", "silver_si", "dollar_dxy", "ust2y_zt", "ust10y_zn", "sp500_es", "nasdaq_nq"];

export function CrossAssetWorkspace({ release }: { release: ReleaseSummary | null }) {
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [windows, setWindows] = useState<WindowsResponse | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<string[]>(CORE_KEYS);

  useEffect(() => {
    if (!release) return;
    setTimeline(null);
    void Promise.all([api.timeline(release.id), api.windows(release.id)]).then(
      ([timelineResult, windowResult]) => {
        setTimeline(timelineResult);
        setWindows(windowResult);
      },
    );
  }, [release?.id]);

  const leaders = useMemo(
    () =>
      [...(windows?.reactions ?? [])]
        .filter((item) => item.lead_rank !== null)
        .sort((left, right) => (left.lead_rank ?? 99) - (right.lead_rank ?? 99))
        .slice(0, 8),
    [windows],
  );

  if (!release || !timeline) {
    return <StateMessage title="正在对齐跨资产时间轴" detail="统一各资产为事件前基准的标准化收益。" />;
  }

  return (
    <div class="workspace">
      <section class="page-heading">
        <div>
          <div class="eyebrow">EVENT-CENTERED CROSS ASSET</div>
          <h1>跨资产反应</h1>
          <p>{release.title} · {release.period_label}。这里围绕事件组织，而不是做普通行情列表。</p>
        </div>
      </section>
      <Panel title="标准化同步时间轴" eyebrow="NORMALIZED RETURN">
        <div class="instrument-toggles">
          {Object.entries(timeline.series).map(([key, item]) => (
            <button
              type="button"
              class={selectedKeys.includes(key) ? "active" : ""}
              onClick={() =>
                setSelectedKeys((current) =>
                  current.includes(key) ? current.filter((itemKey) => itemKey !== key) : [...current, key],
                )
              }
              key={key}
            >
              {item.symbol}
              {item.is_proxy ? <small>代理</small> : null}
            </button>
          ))}
        </div>
        <CrossAssetChart timeline={timeline} selectedKeys={selectedKeys} />
      </Panel>
      <div class="two-column">
        <Panel title="最早观察到的显著反应" eyebrow="LEAD / LAG">
          <div class="leader-list">
            {leaders.map((item) => (
              <article key={`${item.stage_key}-${item.instrument_key}`}>
                <span class="leader-rank">#{item.lead_rank}</span>
                <div>
                  <strong>{item.instrument_title}</strong>
                  <p>{item.stage_key} · {item.latency_seconds ?? "—"} 秒后首次满足阈值</p>
                </div>
                <Badge tone={item.initial_direction === "up" ? "good" : "bad"}>
                  {item.initial_direction}
                </Badge>
              </article>
            ))}
          </div>
          <p class="method-note">这是 60 秒 bar 内的“最早观察”，不是逐笔订单流领先关系。</p>
        </Panel>
        <Panel title="反转与阶段切换" eyebrow="REVERSAL">
          <div class="leader-list">
            {(windows?.reactions ?? [])
              .filter((item) => item.direction_reversal)
              .slice(0, 10)
              .map((item) => (
                <article key={`${item.stage_key}-${item.instrument_key}`}>
                  <span class="leader-rank">↺</span>
                  <div><strong>{item.instrument_title}</strong><p>{item.stage_key} 阶段与上一阶段方向相反</p></div>
                  <Badge tone="warn">反转</Badge>
                </article>
              ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
