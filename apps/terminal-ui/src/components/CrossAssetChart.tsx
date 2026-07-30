import type { TimelineResponse } from "../types";

const COLORS = [
  "#e7b553",
  "#e8e6df",
  "#54c7a4",
  "#ef6f78",
  "#72a7ff",
  "#b594ff",
  "#ff9865",
  "#6ad1e3",
  "#d6df63",
  "#f08ec0",
  "#8aa0b7",
];

export function CrossAssetChart({
  timeline,
  selectedKeys,
}: {
  timeline: TimelineResponse;
  selectedKeys?: string[];
}) {
  const entries = Object.entries(timeline.series).filter(
    ([key]) => !selectedKeys || selectedKeys.includes(key),
  );
  const allPoints = entries.flatMap(([, item]) => item.points);
  if (!allPoints.length) {
    return <div class="chart-empty">这一事件没有可绘制的分钟行情。</div>;
  }
  const start = Math.min(...allPoints.map((point) => Date.parse(point.timestamp)));
  const end = Math.max(...allPoints.map((point) => Date.parse(point.timestamp)));
  const values = allPoints
    .map((point) => point.normalized_percent)
    .filter((value): value is number => value !== null && Number.isFinite(value));
  const range = Math.max(0.1, ...values.map((value) => Math.abs(value)));
  const x = (timestamp: string) => 42 + ((Date.parse(timestamp) - start) / Math.max(1, end - start)) * 918;
  const y = (value: number) => 180 - (value / range) * 138;

  return (
    <div class="cross-chart">
      <svg viewBox="0 0 1000 360" role="img" aria-label="事件前后跨资产标准化收益曲线">
        <rect x="42" y="30" width="918" height="288" rx="8" class="chart-bg" />
        {[0, 0.5, 1].map((ratio) => (
          <line
            key={ratio}
            x1="42"
            y1={42 + ratio * 264}
            x2="960"
            y2={42 + ratio * 264}
            class="grid-line"
          />
        ))}
        <line x1="42" y1={y(0)} x2="960" y2={y(0)} class="zero-line" />
        {timeline.stages.map((stage) => (
          <g key={stage.key}>
            <line
              x1={x(stage.timestamp)}
              y1="30"
              x2={x(stage.timestamp)}
              y2="318"
              class="stage-line"
            />
            <text x={x(stage.timestamp) + 5} y="48" class="stage-label">
              {stage.title.slice(0, 10)}
            </text>
          </g>
        ))}
        {entries.map(([key, item], index) => {
          const sampleEvery = Math.max(1, Math.ceil(item.points.length / 320));
          const points = item.points
            .filter((point, pointIndex) => pointIndex % sampleEvery === 0)
            .filter((point) => point.normalized_percent !== null)
            .map((point) => `${x(point.timestamp)},${y(point.normalized_percent ?? 0)}`)
            .join(" ");
          return (
            <polyline
              key={key}
              points={points}
              fill="none"
              stroke={COLORS[index % COLORS.length]}
              stroke-width="2.25"
              vector-effect="non-scaling-stroke"
            />
          );
        })}
        <text x="4" y="42" class="axis-label">
          +{range.toFixed(2)}%
        </text>
        <text x="10" y={y(0) + 4} class="axis-label">
          0
        </text>
        <text x="4" y="318" class="axis-label">
          -{range.toFixed(2)}%
        </text>
      </svg>
      <div class="chart-legend">
        {entries.map(([key, item], index) => (
          <span key={key}>
            <i style={{ background: COLORS[index % COLORS.length] }} />
            {item.title} {item.is_proxy ? "（代理）" : ""}
          </span>
        ))}
      </div>
      <p class="method-note">{timeline.limitation}</p>
    </div>
  );
}
