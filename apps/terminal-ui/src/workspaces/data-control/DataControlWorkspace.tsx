import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../../api/client";
import { Badge, DetailsDisclosure, Modal, Panel, StateMessage } from "../../components/Primitives";
import type { DataFreshnessResponse, DataProviderStatus, ReleaseSummary } from "../../types";
import type { DatasetCapability } from "../../types/product";

interface ControlData {
  providers: DataProviderStatus[];
  freshness: DataFreshnessResponse;
  systems: Array<Record<string, unknown>>;
  capabilities: DatasetCapability[];
  releases: ReleaseSummary[];
}

type Dialog = "fred" | "market" | "macro" | "event" | null;

const MARKET_INSTRUMENTS = [
  ["gold_gc", "Gold futures"],
  ["sp500_cash", "S&P 500"],
  ["vix_cash", "VIX"],
  ["ust2y_yield_context", "US 2Y yield"],
  ["ust10y_yield_context", "US 10Y yield"],
  ["dollar_broad_context", "Broad dollar"],
  ["wti_spot", "WTI oil"],
  ["brent_spot", "Brent oil"],
] as const;

export function DataControlWorkspace() {
  const [data, setData] = useState<ControlData | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [fredKey, setFredKey] = useState("");
  const [marketInstrument, setMarketInstrument] = useState("gold_gc");
  const [marketSourceUrl, setMarketSourceUrl] = useState("");
  const [marketVerified, setMarketVerified] = useState(false);
  const [macroProvider, setMacroProvider] = useState("manual_official");
  const [macroSourceUrl, setMacroSourceUrl] = useState("");
  const [macroVerified, setMacroVerified] = useState(false);
  const [macroNotes, setMacroNotes] = useState("");
  const [eventReleaseId, setEventReleaseId] = useState("");
  const [eventInstrument, setEventInstrument] = useState("gold_gc");
  const [eventSourceUrl, setEventSourceUrl] = useState("");
  const [eventVerified, setEventVerified] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const marketFileRef = useRef<HTMLInputElement>(null);
  const macroFileRef = useRef<HTMLInputElement>(null);
  const eventFileRef = useRef<HTMLInputElement>(null);

  const reload = async () => {
    const [providers, freshness, systemsPayload, capabilityPayload, releases] = await Promise.all([
      api.dataProviders(),
      api.dataFreshness(),
      api.macroSystems(),
      api.dataCapabilities(),
      api.releases(),
    ]);
    const systems = Array.isArray(systemsPayload.systems)
      ? (systemsPayload.systems as Array<Record<string, unknown>>)
      : [];
    setData({ providers: providers.items, freshness, systems, capabilities: capabilityPayload.items, releases });
  };

  useEffect(() => {
    void reload().catch((error) =>
      setMessage(error instanceof Error ? error.message : "Data Control is temporarily unavailable"),
    );
  }, []);

  const runAction = async (action: () => Promise<string>) => {
    setBusy(true);
    setMessage(null);
    try {
      setMessage(await action());
      await reload();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The data action failed");
    } finally {
      setBusy(false);
    }
  };

  const bootstrap = () =>
    void runAction(async () => {
      const result = await api.bootstrapFree();
      return `Public data sync: ${String(result.status ?? "submitted")}`;
    });

  const syncBlsState = () =>
    void runAction(async () => {
      const end = new Date();
      const start = new Date(end);
      start.setFullYear(end.getFullYear() - 5);
      const result = await api.syncBlsCurrentState(
        start.toISOString().slice(0, 10),
        end.toISOString().slice(0, 10),
      );
      return `BLS current observations: ${String(result.records_written ?? 0)} rows (non-PIT)`;
    });

  const saveFredKey = () => {
    if (!fredKey.trim()) return;
    void runAction(async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        await invoke("save_api_secret", { name: "FRED_API_KEY", value: fredKey.trim() });
        setDialog(null);
        setFredKey("");
        return "FRED Key saved in Windows Credential Manager. Restart WorldState to use ALFRED/PIT.";
      } catch (error) {
        throw new Error(
          error instanceof Error
            ? `Desktop credential storage is unavailable: ${error.message}`
            : "This browser session cannot save a desktop secret",
        );
      }
    });
  };

  const chooseFile = (event: Event, next: Exclude<Dialog, null>) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = "";
    if (file) {
      setSelectedFile(file);
      setDialog(next);
    }
  };

  const importMarket = () => {
    if (!selectedFile) return;
    void runAction(async () => {
      const result = await api.importContextMarketCsv({
        instrument_key: marketInstrument,
        csv_text: await selectedFile.text(),
        provider_key: "manual_csv",
        source_name: selectedFile.name,
        source_url: marketSourceUrl.trim() || undefined,
        verified: marketVerified,
        interval_seconds: 86400,
      });
      setDialog(null);
      setSelectedFile(null);
      return `Imported ${String(result.inserted ?? 0)} observed daily context bars.`;
    });
  };

  const importMacro = () => {
    if (!selectedFile || !macroSourceUrl.trim()) return;
    void runAction(async () => {
      const result = await api.importOfficialMacroCsv({
        csv_text: await selectedFile.text(),
        provider_key: macroProvider,
        source_name: selectedFile.name,
        source_url: macroSourceUrl.trim(),
        verified: macroVerified,
        verification_notes: macroNotes.trim() || undefined,
      });
      setDialog(null);
      setSelectedFile(null);
      return `Imported ${String(result.inserted ?? 0)} observed macro rows; PIT=${String(result.point_in_time ?? false)}.`;
    });
  };

  const importEventBars = () => {
    if (!selectedFile || !eventReleaseId) return;
    void runAction(async () => {
      const result = await api.importMarketBars(eventReleaseId, { instrument_key: eventInstrument, csv_text: await selectedFile.text(), provider_key: "manual_csv", source_name: selectedFile.name, source_url: eventSourceUrl.trim() || undefined, verified: eventVerified, is_fixture: false });
      setDialog(null); setSelectedFile(null);
      return `Imported ${String(result.inserted ?? 0)} event-linked minute bars. Coverage remains subject to validation.`;
    });
  };

  if (!data) {
    return <StateMessage title="Loading Data Control" detail="Checking providers, freshness and observed coverage." />;
  }
  const summary = data.freshness.summary;
  return (
    <div class="workspace data-foundation">
      <section class="page-heading">
        <div>
          <div class="eyebrow">DATA CONTROL · SETTINGS / DATA SOURCES</div>
          <h1>Data sources</h1>
          <p>Connect sources, import official files and inspect freshness. Technical provenance stays available behind details.</p>
        </div>
        <div class="page-heading__actions">
          <input ref={marketFileRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => chooseFile(event, "market")} />
          <input ref={macroFileRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => chooseFile(event, "macro")} />
          <input ref={eventFileRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => chooseFile(event, "event")} />
          <button class="button-secondary" disabled={busy} onClick={() => marketFileRef.current?.click()}>Import market data</button>
          <button class="button-secondary" disabled={busy} onClick={() => macroFileRef.current?.click()}>Import official macro file</button>
          <button class="button-secondary" disabled={busy} onClick={() => eventFileRef.current?.click()}>Import event minute data</button>
          <button class="button-secondary" disabled={busy} onClick={() => setDialog("fred")}>Configure FRED</button>
          <button class="button-secondary" disabled={busy} onClick={syncBlsState}>Sync BLS current</button>
          <button class="button-primary" disabled={busy} onClick={bootstrap}>{busy ? "Syncing…" : "Bootstrap public data"}</button>
        </div>
      </section>
      {message ? <div class="data-notice"><strong>{message}</strong><p>Fixture rows never replace observed rows.</p></div> : null}
      <div class="summary-grid data-summary-grid">
        {Object.entries(summary).map(([status, count]) => (
          <Panel title={status} eyebrow="FRESHNESS" key={status}>
            <div class="big-number">{count}</div>
            <p class="method-note">Current data mode: {data.freshness.data_mode}</p>
          </Panel>
        ))}
      </div>
      <Panel title="Provider status" eyebrow="PUBLIC · CREDENTIAL · BLOCKED">
        <div class="provider-setup-grid">
          {data.providers.map((item) => (
            <article class="provider-card" key={item.provider_id}>
              <header>
                <div><span>{item.provider_id}</span><h3>{item.display_name}</h3></div>
                <Badge tone={item.healthy === true ? "good" : item.healthy === false ? "bad" : "neutral"}>{item.status}</Badge>
              </header>
              <p>{item.configured ? "Configured or public endpoint available" : "Credential or endpoint required"}</p>
              <DetailsDisclosure label="Research details">
                <dl class="detail-grid">
                  <div><dt>Quality</dt><dd>{item.quality_grade ?? "—"}</dd></div>
                  <div><dt>Last success</dt><dd>{item.last_success_at ?? "—"}</dd></div>
                  <div><dt>Capabilities</dt><dd>{item.capabilities.join(" · ")}</dd></div>
                  <div><dt>Note</dt><dd>{item.last_error ?? "No error recorded"}</dd></div>
                </dl>
              </DetailsDisclosure>
            </article>
          ))}
        </div>
      </Panel>
      <Panel title="Macro system coverage" eyebrow="OBSERVED COMPONENT COVERAGE">
        <div class="provider-setup-grid">
          {data.systems.map((system) => (
            <article class="provider-card" key={String(system.key)}>
              <header><div><span>{String(system.key)}</span><h3>{String(system.title)}</h3></div><Badge tone={system.status === "available" ? "good" : system.status === "partial" ? "warn" : "bad"}>{String(system.status)}</Badge></header>
              <p>{String(system.available_components ?? 0)} / {String(system.component_count ?? 0)} observed components</p>
              <DetailsDisclosure label="Coverage details"><small>Coverage {String(system.coverage ?? 0)}</small></DetailsDisclosure>
            </article>
          ))}
        </div>
      </Panel>
      <Panel title="Series freshness" eyebrow="OBSERVED SERIES">
        <div class="freshness-table-wrap"><table class="coverage-table"><thead><tr><th>Series</th><th>Provider</th><th>Status</th><th>Latest period</th><th>Available at</th></tr></thead><tbody>
          {data.freshness.items.slice(0, 120).map((item) => (
            <tr key={item.canonical_key}><td><strong>{item.title}</strong><small>{item.canonical_key}</small></td><td>{item.provider}</td><td><Badge tone={item.status === "LIVE" ? "good" : item.status === "MISSING" ? "bad" : "warn"}>{item.status}</Badge></td><td>{item.latest_period ?? "—"}</td><td>{item.available_at ?? "—"}</td></tr>
          ))}
        </tbody></table></div>
      </Panel>
      <Panel title="Dataset capability inventory" eyebrow="WHAT THE PRODUCT CAN ACTUALLY DO">
        <p class="method-note">Rows alone do not imply event research. Each dataset is classified by coverage, provenance, PIT semantics and eligible workflows.</p>
        <div class="freshness-table-wrap"><table class="coverage-table"><thead><tr><th>Dataset</th><th>Rows</th><th>Coverage</th><th>Source</th><th>Current</th><th>Event intraday</th><th>PIT</th></tr></thead><tbody>
          {data.capabilities.slice(0, 160).map((item) => <tr key={item.dataset_key}><td><strong>{item.label}</strong><small>{item.kind} / {item.canonical_key}</small></td><td>{item.rows}</td><td>{item.coverage_start ?? "—"} → {item.coverage_end ?? "—"}</td><td>{item.source_class}</td><td><Badge tone={item.capabilities.CURRENT_STATE?.available ? "good" : "neutral"}>{item.capabilities.CURRENT_STATE?.status ?? "MISSING"}</Badge></td><td><Badge tone={item.capabilities.EVENT_INTRADAY?.available ? "good" : "neutral"}>{item.capabilities.EVENT_INTRADAY?.status ?? "MISSING"}</Badge></td><td><Badge tone={item.point_in_time ? "good" : "neutral"}>{item.point_in_time ? "YES" : "NO"}</Badge></td></tr>)}
        </tbody></table></div>
      </Panel>

      {dialog === "fred" ? <Modal title="Configure FRED" onClose={() => setDialog(null)}>
        <p class="modal-copy">The public CSV path works without a key. A key enables ALFRED historical vintages and point-in-time research.</p>
        <label class="form-field"><span>FRED API Key</span><input type="password" value={fredKey} onInput={(event) => setFredKey(event.currentTarget.value)} placeholder="Stored only in desktop Credential Manager" /></label>
        <div class="modal-actions"><button class="button-secondary" onClick={() => setDialog(null)}>Cancel</button><button class="button-primary" disabled={!fredKey.trim() || busy} onClick={saveFredKey}>Save key</button></div>
      </Modal> : null}
      {dialog === "market" ? <Modal title="Import market context" onClose={() => { setDialog(null); setSelectedFile(null); }}>
        <p class="modal-copy">Daily context bars support overview changes. They are not minute event-window data.</p>
        <label class="form-field"><span>Asset</span><select value={marketInstrument} onChange={(event) => setMarketInstrument(event.currentTarget.value)}>{MARKET_INSTRUMENTS.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
        <label class="form-field"><span>Source URL (optional)</span><input value={marketSourceUrl} onInput={(event) => setMarketSourceUrl(event.currentTarget.value)} placeholder="https://…" /></label>
        <label class="check-field"><input type="checkbox" checked={marketVerified} onChange={(event) => setMarketVerified(event.currentTarget.checked)} /><span>I checked this file against its source</span></label>
        <div class="modal-actions"><button class="button-secondary" onClick={() => setDialog(null)}>Cancel</button><button class="button-primary" disabled={busy} onClick={importMarket}>Import {selectedFile?.name}</button></div>
      </Modal> : null}
      {dialog === "macro" ? <Modal title="Import official macro file" onClose={() => { setDialog(null); setSelectedFile(null); }}>
        <p class="modal-copy">Use an official Japan, China or other statistics export. The file must include canonical_key, period_start, value and entity_iso3.</p>
        <label class="form-field"><span>Country / provider label</span><input value={macroProvider} onInput={(event) => setMacroProvider(event.currentTarget.value)} placeholder="boj_manual or china_manual" /></label>
        <label class="form-field"><span>Official source URL</span><input required value={macroSourceUrl} onInput={(event) => setMacroSourceUrl(event.currentTarget.value)} placeholder="https://…" /></label>
        <label class="form-field"><span>Verification note</span><textarea value={macroNotes} onInput={(event) => setMacroNotes(event.currentTarget.value)} placeholder="What did you verify?" /></label>
        <label class="check-field"><input type="checkbox" checked={macroVerified} onChange={(event) => setMacroVerified(event.currentTarget.checked)} /><span>I checked this file against its official source</span></label>
        <div class="modal-actions"><button class="button-secondary" onClick={() => setDialog(null)}>Cancel</button><button class="button-primary" disabled={busy || !macroSourceUrl.trim()} onClick={importMacro}>Import {selectedFile?.name}</button></div>
      </Modal> : null}
      {dialog === "event" ? <Modal title="Import event minute data" onClose={() => { setDialog(null); setSelectedFile(null); }}>
        <p class="modal-copy">This wizard links observed minute bars to one release. It does not accept fixture data and does not infer missing bars.</p>
        <label class="form-field"><span>Release</span><select value={eventReleaseId} onChange={(event) => setEventReleaseId(event.currentTarget.value)}><option value="">Select a release</option>{data.releases.filter((item) => item.status === "released").slice(0, 120).map((item) => <option key={item.id} value={item.id}>{item.title} / {item.period_label}</option>)}</select></label>
        <label class="form-field"><span>Asset</span><select value={eventInstrument} onChange={(event) => setEventInstrument(event.currentTarget.value)}>{MARKET_INSTRUMENTS.map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
        <label class="form-field"><span>Source URL (optional)</span><input value={eventSourceUrl} onInput={(event) => setEventSourceUrl(event.currentTarget.value)} placeholder="Legal source for this file" /></label>
        <label class="check-field"><input type="checkbox" checked={eventVerified} onChange={(event) => setEventVerified(event.currentTarget.checked)} /><span>I checked timestamps, timezone, duplicates and source</span></label>
        <div class="modal-actions"><button class="button-secondary" onClick={() => setDialog(null)}>Cancel</button><button class="button-primary" disabled={busy || !eventReleaseId} onClick={importEventBars}>Import {selectedFile?.name}</button></div>
      </Modal> : null}
    </div>
  );
}
