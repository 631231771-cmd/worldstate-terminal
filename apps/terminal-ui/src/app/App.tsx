import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../api/client";
import { Badge, StateMessage } from "../components/Primitives";
import { WorkspaceBoundary } from "../components/WorkspaceBoundary";
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

interface NavItem {
  key: ViewKey;
  label: string;
  index: string;
  note: string;
}

const NAV_GROUPS: Array<{ key: string; label: string; items: NavItem[] }> = [
  { key: "overview", label: "Overview", items: [{ key: "today", label: "Today", index: "01", note: "Daily brief" }] },
  { key: "markets", label: "Markets", items: [
    { key: "markets", label: "Markets", index: "02", note: "Cross-asset context" },
    { key: "cross-asset", label: "Cross Asset", index: "03", note: "Event reaction" },
  ] },
  { key: "macro", label: "Macro", items: [
    { key: "world-state", label: "World State", index: "04", note: "Regime and drivers" },
    { key: "countries", label: "Countries", index: "05", note: "Global context" },
    { key: "series", label: "Series", index: "06", note: "Macro history" },
  ] },
  { key: "events", label: "Events", items: [
    { key: "releases", label: "Calendar / Releases", index: "07", note: "Actual and consensus" },
    { key: "event-lab", label: "Event Lab", index: "08", note: "Full review" },
  ] },
  { key: "research", label: "Research", items: [{ key: "research", label: "Thesis", index: "09", note: "Research notebook" }] },
  { key: "advanced", label: "Advanced", items: [
    { key: "data-control", label: "Data Sources", index: "A1", note: "Settings and sync" },
    { key: "data-methods", label: "Data & Methods", index: "A2", note: "Quality and boundaries" },
  ] },
];
const NAVIGATION = NAV_GROUPS.flatMap((group) => group.items);

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
  const [learningMode, setLearningMode] = useState(
    () => window.localStorage.getItem("worldstate.learning_mode") === "on",
  );

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [releaseResult, healthResult] = await Promise.allSettled([api.releases(), api.health()]);
      if (releaseResult.status === "rejected") throw releaseResult.reason;
      setReleases(releaseResult.value);
      setHealth(healthResult.status === "fulfilled" ? healthResult.value : null);
      setSelectedReleaseId((current) => current ?? releaseResult.value[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Research service is unavailable");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);
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
  const toggleLearningMode = () => {
    setLearningMode((current) => {
      const next = !current;
      window.localStorage.setItem("worldstate.learning_mode", next ? "on" : "off");
      return next;
    });
  };
  const eventView = view === "releases" || view === "event-lab" || view === "cross-asset";

  return (
    <div class="terminal-shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand__mark">W<span>S</span></div><div><strong>WorldState</strong><span>Macro Research Terminal</span></div></div>
        <nav aria-label="Primary navigation">
          {NAV_GROUPS.map((group) => <div class="nav-group" key={group.key}>
            <span class="nav-group__label">{group.label}</span>
            {group.items.map((item) => <button type="button" key={item.key} class={view === item.key ? "nav-item nav-item--active" : "nav-item"} onClick={() => setView(item.key)}>
              <span class="nav-item__index">{item.index}</span><span><strong>{item.label}</strong><small>{item.note}</small></span>
            </button>)}
          </div>)}
        </nav>
        <div class="sidebar__method"><span>RESEARCH CHAIN</span><strong>Facts → Reaction → History → Inference</strong><p>Details remain available, but the default view stays focused on what changed and why it matters.</p></div>
      </aside>
      <main class="main">
        <header class="topbar">
          <div><span class="topbar__kicker">WORLDSTATE · MACRO RESEARCH TERMINAL</span><strong>{NAVIGATION.find((item) => item.key === view)?.label}</strong></div>
          <div class="topbar__status">
            {eventView && selected ? <label><span>Research event</span><select value={selected.id} onChange={(event) => setSelectedReleaseId((event.currentTarget as HTMLSelectElement).value)}>{releases.map((release) => <option value={release.id} key={release.id}>{release.title} · {release.period_label}</option>)}</select></label> : null}
            <button type="button" class={learningMode ? "mode-toggle mode-toggle--active" : "mode-toggle"} onClick={toggleLearningMode} title="Show short contextual explanations">{learningMode ? "Learning on" : "Learning off"}</button>
            <Badge tone={health?.database.status === "ok" ? "good" : "warn"}>{health?.database.status === "ok" ? "Service online" : "Service unavailable"}</Badge>
            {health?.generated_at ? <span class="topbar__updated">Updated {new Date(health.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span> : null}
          </div>
        </header>
        {loading ? <StateMessage title="Loading research" detail="Reading releases, analysis runs and data quality." /> : error ? <StateMessage title="Research service unavailable" detail={error} action={<button type="button" class="primary-button" onClick={() => void refresh()}>Retry</button>} /> : <WorkspaceBoundary>
          {view === "today" ? <TodayWorkspace releases={releases} health={health} onOpen={openRelease} learningMode={learningMode} /> : null}
          {view === "world-state" ? <WorldStateWorkspace /> : null}
          {view === "markets" ? <MarketsWorkspace /> : null}
          {view === "releases" ? <ReleasesWorkspace releases={releases} onOpen={openRelease} /> : null}
          {view === "event-lab" ? <EventLabWorkspace release={selected} onRefresh={refresh} /> : null}
          {view === "cross-asset" ? <CrossAssetWorkspace release={selected} /> : null}
          {view === "series" ? <SeriesWorkspace /> : null}
          {view === "countries" ? <CountriesWorkspace /> : null}
          {view === "research" ? <ResearchWorkspace /> : null}
          {view === "data-methods" ? <DataMethodsWorkspace /> : null}
          {view === "data-control" ? <DataControlWorkspace /> : null}
        </WorkspaceBoundary>}
      </main>
    </div>
  );
}
