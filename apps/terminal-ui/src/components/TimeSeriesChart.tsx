import { AreaSeries, ColorType, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";

export type ChartHorizon = "1w" | "1m" | "3m" | "1y";

interface ChartPoint {
  time: string;
  value: number;
}

const HORIZON_DAYS: Record<ChartHorizon, number> = {
  "1w": 8,
  "1m": 32,
  "3m": 94,
  "1y": 367,
};

export function TimeSeriesChart({ points, horizon }: { points: ChartPoint[]; horizon: ChartHorizon }) {
  const container = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<{ time: string; value: number } | null>(null);
  const visible = useMemo(() => {
    const valid = points
      .filter((point) => Number.isFinite(point.value) && !Number.isNaN(Date.parse(point.time)))
      .sort((left, right) => Date.parse(left.time) - Date.parse(right.time));
    if (!valid.length) return [];
    const latestPoint = valid.at(-1)!;
    const cutoff = Date.parse(latestPoint.time) - HORIZON_DAYS[horizon] * 86400_000;
    return valid.filter((point) => Date.parse(point.time) >= cutoff);
  }, [points, horizon]);

  useEffect(() => {
    if (!container.current || !visible.length) return;
    const chart = createChart(container.current, {
      autoSize: true,
      height: 270,
      layout: {
        background: { type: ColorType.Solid, color: "#0d1216" },
        textColor: "#84909a",
        fontFamily: "IBM Plex Sans, Noto Sans SC, sans-serif",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "rgba(115, 128, 140, 0.08)" },
        horzLines: { color: "rgba(115, 128, 140, 0.08)" },
      },
      crosshair: {
        vertLine: { color: "rgba(218, 172, 74, 0.55)", labelBackgroundColor: "#926f25" },
        horzLine: { color: "rgba(218, 172, 74, 0.35)", labelBackgroundColor: "#926f25" },
      },
      rightPriceScale: { borderColor: "rgba(115, 128, 140, 0.2)" },
      timeScale: { borderColor: "rgba(115, 128, 140, 0.2)", timeVisible: false },
      localization: { locale: "zh-CN" },
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#d6a947",
      topColor: "rgba(214, 169, 71, 0.28)",
      bottomColor: "rgba(214, 169, 71, 0.01)",
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    series.setData(visible.map((point) => ({
      time: Math.floor(Date.parse(point.time) / 1000) as UTCTimestamp,
      value: point.value,
    })));
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((parameter) => {
      const value = parameter.seriesData.get(series);
      if (!parameter.time || !value || !("value" in value)) {
        setHovered(null);
        return;
      }
      const timestamp = typeof parameter.time === "number"
        ? new Date(parameter.time * 1000)
        : new Date(String(parameter.time));
      setHovered({ time: timestamp.toLocaleDateString("zh-CN"), value: value.value });
    });
    return () => chart.remove();
  }, [visible]);

  if (!visible.length) return <div class="chart-empty">当前区间没有可绘制的连续观测。</div>;
  const latestPoint = visible.at(-1)!;
  const latest = hovered ?? {
    time: new Date(latestPoint.time).toLocaleDateString("zh-CN"),
    value: latestPoint.value,
  };
  return <div class="timeseries-chart">
    <div class="timeseries-chart__tooltip"><span>{latest.time}</span><strong>{latest.value.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}</strong></div>
    <div class="timeseries-chart__canvas" ref={container} />
    <small class="timeseries-chart__credit">Charts by TradingView Lightweight Charts™</small>
  </div>;
}
