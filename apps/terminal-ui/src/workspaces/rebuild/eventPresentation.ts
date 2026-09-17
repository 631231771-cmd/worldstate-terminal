export interface EventPresentationInput {
  event: { status: string; type: string };
  actual: {
    available: boolean;
    indicators: Array<{ actual: number | null }>;
  };
  surprise: {
    available: boolean;
    classification: string | null;
    direction: string | null;
  };
}

export interface EventPresentationState {
  title: string;
  detail: string;
  actualCount: number;
  actualProgress: string;
}

export function eventPresentationState(
  input: EventPresentationInput,
  directionLabel: (value: string | null) => string,
): EventPresentationState {
  const actualCount = input.actual.indicators.filter((item) => item.actual != null).length;
  const actualProgress = input.actual.available
    ? "已获取"
    : actualCount > 0
      ? `部分已获取（${actualCount} 项）`
      : input.event.status === "scheduled"
        ? "待发布"
        : "待采集";

  if (input.surprise.available) {
    return {
      title: input.surprise.classification ?? directionLabel(input.surprise.direction),
      detail: "先看哪些指标偏离预期，再核对市场是否按同一条路径反应。",
      actualCount,
      actualProgress,
    };
  }
  if (input.actual.available) {
    return {
      title: "实际值已到，事前预期尚未齐备",
      detail: "打开来源核对已有数据，缺少的输入不会被估算填满。",
      actualCount,
      actualProgress,
    };
  }
  if (actualCount > 0) {
    const isFomc = input.event.type === "FOMC";
    return {
      title: isFomc ? "利率决定已发布，阶段资料仍待补齐" : "首批实际值已到，事件输入仍待补齐",
      detail: isFomc
        ? "已记录官方利率决定；声明或发布会语气等阶段输入尚未齐全，不会被估算填满。"
        : "已记录官方发布值；仍缺的指标或阶段不会被估算填满。",
      actualCount,
      actualProgress,
    };
  }
  if (input.event.status === "scheduled") {
    return {
      title: "等待正式发布",
      detail: "发布前先记录市场预期；发布后的实际值不会被提前填入。",
      actualCount,
      actualProgress,
    };
  }
  return {
    title: "官方事件已发布，实际值仍待采集",
    detail: "系统已确认发布时间，但尚未取得可核验的正式数值。",
    actualCount,
    actualProgress,
  };
}
