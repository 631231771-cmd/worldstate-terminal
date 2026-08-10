import { useMemo, useState } from "preact/hooks";
import type { ReleaseDetail, ReleaseSummary } from "../../types";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Modal, Panel, StateMessage } from "../../components/Primitives";
import { EventLabWorkspace } from "../event-lab/EventLabWorkspace";

type EventTab = "upcoming" | "recent" | "all";

function eventTone(item: ReleaseSummary): "good" | "warn" | "neutral" | "info" {
  if (item.analysis_status === "completed" && item.reproducibility_status === "complete") return "good";
  if (item.status === "scheduled") return "info";
  return "warn";
}

function eventType(item: ReleaseSummary): string {
  if (item.release_type === "US_CPI") return "CPI";
  if (item.release_type === "US_NFP") return "NFP";
  if (item.release_type === "FOMC") return "FOMC";
  return item.release_type;
}

function localDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function localTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function EventsBoard({
  releases,
  selected,
  detail,
  onSelect,
  onOpenLab,
  onOpenDataSources,
}: {
  releases: ReleaseSummary[];
  selected: ReleaseSummary | null;
  detail: ReleaseDetail | null;
  onSelect: (release: ReleaseSummary) => void;
  onOpenLab: () => void;
  onOpenDataSources: () => void;
}) {
  const [labOpen, setLabOpen] = useState(false);
  const [eventTab, setEventTab] = useState<EventTab>("upcoming");
  const [consensusOpen, setConsensusOpen] = useState(false);
  const [indicatorKey, setIndicatorKey] = useState("");
  const [consensusValue, setConsensusValue] = useState("");
  const [sourceName, setSourceName] = useState("Manual consensus");
  const [sourceUrl, setSourceUrl] = useState("");
  const [capturedAt, setCapturedAt] = useState(new Date().toISOString().slice(0, 16));
  const [consensusError, setConsensusError] = useState<string | null>(null);
  const [savingConsensus, setSavingConsensus] = useState(false);

  const visibleReleases = useMemo(() => {
    const sorted = [...releases].sort((a, b) => Date.parse(b.scheduled_at) - Date.parse(a.scheduled_at));
    if (eventTab === "all") return sorted.slice(0, 80);
    if (eventTab === "recent") return sorted.filter((item) => item.status === "released").slice(0, 80);
    return sorted.filter((item) => item.status === "scheduled").slice(0, 80);
  }, [eventTab, releases]);

  if (!releases.length) {
    return (
      <StateMessage
        title="No macro events"
        detail="Load an official calendar in Data Sources."
        action={<button type="button" class="button-primary" onClick={onOpenDataSources}>Open Data Sources</button>}
      />
    );
  }

  if (labOpen && selected) {
    return (
      <div class="workspace workspace--product">
        <button type="button" class="button-secondary" onClick={() => setLabOpen(false)}>← Back to Events</button>
        <EventLabWorkspace release={selected} onRefresh={async () => undefined} />
      </div>
    );
  }

  const hasActual = detail ? Object.values(detail.values).some((value) => value.actual != null) : false;
  const hasConsensus = detail ? Object.values(detail.values).some((value) => value.consensus != null) : false;

  async function saveConsensus(event: Event) {
    event.preventDefault();
    if (!selected) return;
    setConsensusError(null);
    setSavingConsensus(true);
    try {
      await api.appendConsensus(selected.id, {
        indicator_key: indicatorKey.trim(),
        consensus_value: Number(consensusValue),
        source_name: sourceName.trim() || "Manual consensus",
        source_url: sourceUrl.trim() || undefined,
        captured_at: new Date(capturedAt).toISOString(),
        quality_grade: "C",
        is_manual: true,
      });
      setConsensusOpen(false);
      setIndicatorKey("");
      setConsensusValue("");
      onSelect(selected);
    } catch (error) {
      setConsensusError(error instanceof Error ? error.message : "Consensus could not be saved.");
    } finally {
      setSavingConsensus(false);
    }
  }

  return (
    <div class="workspace workspace--product">
      <section class="page-heading page-heading--compact">
        <div>
          <div class="eyebrow">EVENTS / WORKFLOW</div>
          <h1>Macro events</h1>
          <p>Read what happened, what was expected, the reaction, context, and evidence in sequence.</p>
        </div>
        <div class="page-heading__aside"><Badge tone="info">{releases.length} events</Badge></div>
      </section>

      <div class="events-layout">
        <Panel title="Event list" eyebrow="CALENDAR / RELEASES">
          <div class="tabs-bar" role="tablist" aria-label="Event filter">
            {(["upcoming", "recent", "all"] as EventTab[]).map((tab) => (
              <button type="button" class={eventTab === tab ? "active" : ""} onClick={() => setEventTab(tab)} role="tab" aria-selected={eventTab === tab}>
                {tab === "upcoming" ? "Upcoming" : tab === "recent" ? "Recent" : "All"}
              </button>
            ))}
          </div>
          <div class="event-list">
            {visibleReleases.length ? visibleReleases.map((item) => (
              <button
                type="button"
                class={selected?.id === item.id ? "event-list__row event-list__row--active" : "event-list__row"}
                key={item.id}
                onClick={() => { setLabOpen(false); onSelect(item); }}
              >
                <span class="event-list__date">{localDate(item.scheduled_at)}</span>
                <span><strong>{eventType(item)}</strong><small>{localTime(item.scheduled_at)} / {item.period_label}</small></span>
                <Badge tone={eventTone(item)}>{item.status === "scheduled" ? "Upcoming" : item.status === "released" ? "Released" : item.status}</Badge>
              </button>
            )) : <div class="empty-action"><div><h3>No events in this view</h3><p>Switch to All to inspect the full release calendar.</p></div></div>}
          </div>
        </Panel>

        <Panel title={selected ? `${eventType(selected)} / ${selected.period_label}` : "Select an event"} eyebrow="EVENT DETAIL">
          {selected ? (
            <div class="event-detail">
              <div class="event-detail__headline"><strong>{eventType(selected)}</strong><span>{new Date(selected.scheduled_at).toLocaleString()}</span><Badge tone={eventTone(selected)}>{selected.status}</Badge></div>
              <div class="board-grid board-grid--markets">
                <div class="metric-tile"><span class="metric-tile__label">Actual</span><strong class="metric-tile__value">{hasActual ? "Recorded" : "—"}</strong><span class="metric-tile__meta">{hasActual ? "Release value available" : "Not released or missing"}</span></div>
                <div class="metric-tile"><span class="metric-tile__label">Consensus</span><strong class="metric-tile__value">{hasConsensus ? "Recorded" : "—"}</strong><span class="metric-tile__meta">{hasConsensus ? "Pre-T0 snapshot" : "Add pre-T0 consensus"}</span></div>
                <div class="metric-tile"><span class="metric-tile__label">Market reaction</span><strong class="metric-tile__value">{detail?.latest_analysis ? "Eligible" : "—"}</strong><span class="metric-tile__meta">{detail?.latest_analysis ? "Analysis available" : "Import minute data"}</span></div>
              </div>
              {!hasConsensus ? (
                <div class="empty-action">
                  <div><h3>No pre-release expectation recorded</h3><p>Add consensus before T0 to make Surprise eligible.</p></div>
                  <button type="button" class="button-primary" onClick={() => { setConsensusError(null); setConsensusOpen(true); }}>Add Consensus</button>
                </div>
              ) : null}
              <DetailsDisclosure label="Advanced event details"><dl class="detail-grid"><div><dt>Status</dt><dd>{selected.status}</dd></div><div><dt>Data mode</dt><dd>{selected.data_mode}</dd></div><div><dt>Clean window</dt><dd>{selected.clean_window ? "Yes" : "No / unverified"}</dd></div><div><dt>Contamination</dt><dd>{selected.contamination_level}</dd></div></dl></DetailsDisclosure>
              {selected.analysis_status === "completed" ? <button type="button" class="button-primary" onClick={() => { setLabOpen(true); onOpenLab(); }}>Open Event Lab</button> : null}
            </div>
          ) : <div class="empty-action"><div><h3>Select an event to begin</h3><p>Completed, released events are preferred for research replay.</p></div></div>}
        </Panel>
      </div>

      {consensusOpen && selected ? (
        <Modal title={`Add consensus · ${eventType(selected)}`} onClose={() => setConsensusOpen(false)}>
          <form class="form-stack" onSubmit={saveConsensus}>
            <label>Indicator key<input required value={indicatorKey} onInput={(event) => setIndicatorKey((event.currentTarget as HTMLInputElement).value)} placeholder="headline_cpi_mom" /></label>
            <label>Consensus value<input required type="number" step="any" value={consensusValue} onInput={(event) => setConsensusValue((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>Captured at (local time)<input required type="datetime-local" value={capturedAt} onInput={(event) => setCapturedAt((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>Source<input required value={sourceName} onInput={(event) => setSourceName((event.currentTarget as HTMLInputElement).value)} /></label>
            <label>Source URL<input type="url" value={sourceUrl} onInput={(event) => setSourceUrl((event.currentTarget as HTMLInputElement).value)} placeholder="https://…" /></label>
            {consensusError ? <p class="form-error">{consensusError}</p> : null}
            <div class="modal-actions"><button type="button" class="button-secondary" onClick={() => setConsensusOpen(false)}>Cancel</button><button type="submit" class="button-primary" disabled={savingConsensus}>{savingConsensus ? "Saving…" : "Save consensus"}</button></div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}
