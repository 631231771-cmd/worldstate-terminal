import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../api/client";
import { Badge, StateMessage } from "../components/Primitives";
import type { ReleaseSummary, ViewKey } from "../types";
import { CrossAssetWorkspace } from "../workspaces/cross-asset/CrossAssetWorkspace";
import { CountriesWorkspace } from "../workspaces/countries/CountriesWorkspace";
import { DataMethodsWorkspace } from "../workspaces/data-methods/DataMethodsWorkspace";
import { DataControlWorkspace } from "../workspaces/data-control/DataControlWorkspace";
import { EventLabWorkspace } from "../workspaces/event-lab/EventLabWorkspace";
import { MarketsWorkspace } from "../workspaces/markets/MarketsWorkspace";
import { ReleasesWorkspace } from "../workspaces/releases/ReleasesWorkspace";
import { ResearchWorkspace } from "../workspaces/research/ResearchWorkspace";
import { SeriesWorkspace } from "../workspaces/series/SeriesWorkspace";
import { TodayWorkspace } from "../workspaces/today/TodayWorkspace";
import { WorldStateWorkspace } from "../workspaces/world-state/WorldStateWorkspace";

const NAVIGATION: Array<{ key: ViewKey; label: string; index: string; note: string }> = [
  { key: "data-control", label: "数据控制中心", index: "11", note: "同步与新鲜度" },
  { key: "today", label: "今日", index: "01", note: "研究入口" },
  { key: "world-state", label: "宏观状态", index: "02", note: "增长与通胀" },
  { key: "markets", label: "市场状态", index: "03", note: "跨资产确认" },
  { key: "releases", label: "宏观发布", index: "04", note: "实际值与共识" },
  { key: "event-lab", label: "事件实验室", index: "05", note: "完整复盘" },
  { key: "cross-asset", label: "跨资产", index: "06", note: "同轴反应" },
  { key: "series", label: "宏观序列", index: "07", note: "时间序列" },
  { key: "countries", label: "全球宏观", index: "08", note: "国家概览" },
  { key: "research", label: "研究判断", index: "09", note: "Thesis Book" },
  { key: "data-methods", label: "数据与方法", index: "10", note: "质量与边界" },
];

function initialView(): ViewKey {
  const value = window.location.hash.replace("#", "").split("?")[0];
  return NAVIGATION.some((item) => item.key === value) ? (value as ViewKey) : "today";
}

function initialRelease(): string | null {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("release");
}

export function App() {
  const [view, setView] = useState<ViewKey>(initialView);
  const [releases, setReleases] = useState<ReleaseSummary[]>([]);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(initialRelease);
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [releaseRows, healthResult] = await Promise.all([api.releases(), api.health()]);
      setReleases(releaseRows);
      setHealth(healthResult);
      setSelectedReleaseId((current) => current ?? releaseRows[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "研究服务暂时无法连接。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const query = selectedReleaseId ? `?release=${encodeURIComponent(selectedReleaseId)}` : "";
    window.history.replaceState(null, "", `#${view}${query}`);
  }, [view, selectedReleaseId]);

  const selected = useMemo(
    () => releases.find((item) => item.id === selectedReleaseId) ?? releases[0] ?? null,
    [releases, selectedReleaseId],
  );

  const openRelease = (releaseId: string, destination: ViewKey = "event-lab") => {
    setSelectedReleaseId(releaseId);
    setView(destination);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div class="terminal-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand__mark">W<span>S</span></div>
          <div>
            <strong>WorldState</strong>
            <span>Macro Research Terminal</span>
          </div>
        </div>
        <nav aria-label="一级研究入口">
          {NAVIGATION.map((item) => (
            <button
              type="button"
              key={item.key}
              class={view === item.key ? "nav-item nav-item--active" : "nav-item"}
              onClick={() => setView(item.key)}
            >
              <span class="nav-item__index">{item.index}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.note}</small>
              </span>
            </button>
          ))}
        </nav>
        <div class="sidebar__method">
          <span>研究顺序</span>
          <strong>事实 → 反应 → 历史 → 推断</strong>
          <p>不把相关性写成唯一因果，不隐藏 fixture 与代理资产。</p>
        </div>
      </aside>

      <main class="main">
        <header class="topbar">
          <div>
            <span class="topbar__kicker">个人宏观研究工作台</span>
            <strong>{NAVIGATION.find((item) => item.key === view)?.label}</strong>
          </div>
          <div class="topbar__status">
            {selected ? (
              <label>
                <span>当前研究事件</span>
                <select
                  value={selected.id}
                  onChange={(event) =>
                    setSelectedReleaseId((event.currentTarget as HTMLSelectElement).value)
                  }
                >
                  {releases.map((release) => (
                    <option value={release.id} key={release.id}>
                      {release.title} · {release.period_label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <Badge tone={health?.database.status === "ok" ? "good" : "warn"}>
              {health?.database.status === "ok" ? "研究服务在线" : "服务未连接"}
            </Badge>
          </div>
        </header>

        {loading ? (
          <StateMessage title="正在装载研究证据" detail="读取宏观发布、分析运行与数据质量记录。" />
        ) : error ? (
          <StateMessage
            title="无法连接本地研究服务"
            detail={`${error} 请确认 Research API 已启动，随后重试。`}
            action={
              <button type="button" class="primary-button" onClick={() => void refresh()}>
                重新连接
              </button>
            }
          />
        ) : (
          <>
            {view === "today" ? (
              <TodayWorkspace releases={releases} health={health} onOpen={openRelease} />
            ) : null}
            {view === "world-state" ? <WorldStateWorkspace /> : null}
            {view === "markets" ? <MarketsWorkspace /> : null}
            {view === "releases" ? (
              <ReleasesWorkspace releases={releases} onOpen={openRelease} />
            ) : null}
            {view === "event-lab" ? (
              <EventLabWorkspace release={selected} onRefresh={refresh} />
            ) : null}
            {view === "cross-asset" ? <CrossAssetWorkspace release={selected} /> : null}
            {view === "series" ? <SeriesWorkspace /> : null}
            {view === "countries" ? <CountriesWorkspace /> : null}
            {view === "research" ? <ResearchWorkspace /> : null}
            {view === "data-methods" ? <DataMethodsWorkspace /> : null}
            {view === "data-control" ? <DataControlWorkspace /> : null}
          </>
        )}
      </main>
    </div>
  );
}
