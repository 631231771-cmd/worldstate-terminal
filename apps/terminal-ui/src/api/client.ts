import type {
  BackfillEstimate,
  BackfillJob,
  BackfillRequest,
  DataCoverageResponse,
  DataProvidersResponse,
  ExplanationsResponse,
  HistoricalResponse,
  Instrument,
  ReleaseDetail,
  ReleaseSummary,
  ResearchClaim,
  TimelineResponse,
  WindowsResponse,
  DailyBriefResponse,
  WorldStateResponse,
  DataFreshnessResponse,
} from "../types";
import type { ConsensusCsvPreview, DatasetCapability, EventMinutePreview } from "../types/product";
import { productApi } from "./product";
import { request } from "./transport";

export { API_BASE, ApiError } from "./transport";

export const api = {
  ...productApi,
  health: () =>
    request<{
      status: string;
      version: string;
      generated_at?: string;
      database: { status: string };
      methodology_version: string;
      ai_provider: string;
    }>("/v2/health"),
  today: () =>
    request<{
      date: string;
      scheduled_releases: ReleaseSummary[];
      latest_research: ReleaseSummary[];
      question: string;
      data_note: string;
    }>("/v2/today"),
  dailyBrief: () => request<DailyBriefResponse>("/v2/daily-brief"),
  worldState: () => request<WorldStateResponse>("/v2/world-state"),
  globalMacro: () => request<Record<string, unknown>>("/v2/global-macro"),
  macroSystems: () => request<Record<string, unknown>>("/v2/macro-systems"),
  marketDashboard: (horizon = "1d") =>
    request<Record<string, unknown> & { items: Array<Record<string, unknown>> }>(
      `/v2/market-dashboard?horizon=${horizon}`,
    ),
  series: (query = "") =>
    request<Array<Record<string, unknown>>>(`/v2/series?q=${encodeURIComponent(query)}`),
  seriesHistory: (key: string, transform = "raw") =>
    request<Record<string, unknown>>(
      `/v2/series/${encodeURIComponent(key)}?transform=${transform}`,
    ),
  theses: () => request<Array<Record<string, unknown>>>('/v2/theses'),
  createThesis: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>('/v2/theses', { method: 'POST', body: JSON.stringify(payload) }),
  evaluateThesis: (id: string) => request<Record<string, unknown>>(`/v2/theses/${id}/evaluate`),
  releases: () => request<ReleaseSummary[]>("/v2/releases?limit=500"),
  release: (id: string) => request<ReleaseDetail>(`/v2/releases/${id}`),
  appendConsensus: (releaseId: string, payload: {
    indicator_key: string;
    consensus_value: number;
    source_name: string;
    source_url?: string;
    captured_at: string;
    quality_grade?: string;
    is_manual?: boolean;
    verification_notes?: string;
  }) => request<{ release_id: string; snapshot_id: string; status: string }>(
    `/v2/releases/${encodeURIComponent(releaseId)}/consensus`,
    { method: "POST", body: JSON.stringify(payload) },
  ),
  previewConsensusCsv: (releaseId: string, csvText: string) =>
    request<ConsensusCsvPreview>(
      `/v2/releases/${encodeURIComponent(releaseId)}/consensus/import-csv/preview`,
      { method: "POST", body: JSON.stringify({ csv_text: csvText }) },
    ),
  importConsensusCsv: (releaseId: string, csvText: string) =>
    request<{ release_id: string; inserted: number; warnings: string[]; preview_summary: ConsensusCsvPreview["summary"] }>(
      `/v2/releases/${encodeURIComponent(releaseId)}/consensus/import-csv`,
      { method: "POST", body: JSON.stringify({ csv_text: csvText }) },
    ),
  windows: (id: string) => request<WindowsResponse>(`/v2/releases/${id}/windows`),
  timeline: (id: string) => request<TimelineResponse>(`/v2/releases/${id}/timeline`),
  historical: (id: string) =>
    request<HistoricalResponse>(`/v2/releases/${id}/historical-matches`),
  explanations: (id: string) =>
    request<ExplanationsResponse>(`/v2/releases/${id}/explanations`),
  claims: (runId: string) =>
    request<{ run_id: string; items: ResearchClaim[] }>(`/v2/analysis-runs/${runId}/claims`),
  instruments: () => request<Instrument[]>("/v2/instruments"),
  dataQuality: () => request<Record<string, unknown>>("/v2/data-quality"),
  providerRuns: () => request<Array<Record<string, unknown>>>("/v2/provider-runs"),
  dataProviders: () => request<DataProvidersResponse>("/v2/data/providers"),
  dataCoverage: () => request<DataCoverageResponse>("/v2/data/coverage"),
  dataFreshness: () => request<DataFreshnessResponse>("/v2/data/freshness"),
  dataCapabilities: (dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<{ as_of: string; data_mode: string; items: DatasetCapability[]; summary: Record<string, number>; limitations: string[] }>(
      `/v2/data/capabilities?data_mode=${dataMode}`,
    ),
  syncPublic: (start_date: string, end_date: string) =>
    request<Record<string, unknown>>(
      "/v2/data/sync/public",
      { method: "POST", body: JSON.stringify({ start_date, end_date }) },
      [207, 424],
    ),
  bootstrapFree: () =>
    request<Record<string, unknown>>("/v2/data/bootstrap-free", { method: "POST" }, [207, 424]),
  syncBlsCurrentState: (start_date: string, end_date: string) =>
    request<Record<string, unknown>>(
      "/v2/data/sync/bls-current-state",
      { method: "POST", body: JSON.stringify({ start_date, end_date }) },
      [207, 424],
    ),
  importContextMarketCsv: (payload: {
    instrument_key: string;
    csv_text: string;
    provider_key?: string;
    source_name?: string;
    source_url?: string;
    verified?: boolean;
    interval_seconds?: number;
  }) =>
    request<Record<string, unknown>>(
      "/v2/market-bars/import-context",
      { method: "POST", body: JSON.stringify(payload) },
      [207, 424],
    ),
  importMarketBars: (releaseId: string, payload: {
    instrument_key: string;
    csv_text: string;
    provider_key?: string;
    source_name?: string;
    source_url?: string;
    verified?: boolean;
    is_fixture?: boolean;
    timezone?: string;
    column_mapping?: Record<string, string>;
  }) => request<Record<string, unknown>>(
    `/v2/releases/${encodeURIComponent(releaseId)}/market-bars/import`,
    { method: "POST", body: JSON.stringify(payload) },
    [207, 424],
  ),
  previewMarketBars: (releaseId: string, payload: {
    instrument_key: string;
    csv_text: string;
    provider_key?: string;
    source_name?: string;
    source_url?: string;
    verified?: boolean;
    is_fixture?: boolean;
    timezone?: string;
    column_mapping?: Record<string, string>;
  }) => request<EventMinutePreview>(
    `/v2/releases/${encodeURIComponent(releaseId)}/market-bars/preview`,
    { method: "POST", body: JSON.stringify(payload) },
  ),
  importOfficialMacroCsv: (payload: {
    csv_text: string;
    provider_key?: string;
    source_name?: string;
    source_url: string;
    verified?: boolean;
    verification_notes?: string;
  }) =>
    request<Record<string, unknown>>(
      "/v2/data/macro-series/import-official-csv",
      { method: "POST", body: JSON.stringify(payload) },
      [207, 424],
    ),
  estimateBackfill: (input: BackfillRequest) => {
    const query = new URLSearchParams({
      start_date: input.start_date,
      end_date: input.end_date,
      event_types: input.event_types.join(","),
      assets: input.assets.join(","),
    });
    return request<BackfillEstimate>(`/v2/data/backfill/estimate?${query.toString()}`);
  },
  startBackfill: (input: BackfillRequest & { estimate_id?: string | null }) =>
    request<BackfillJob>(
      "/v2/data/backfill",
      {
        method: "POST",
        body: JSON.stringify(input),
      },
      [424],
    ),
  backfillJob: (id: string) => request<BackfillJob>(`/v2/data/backfill/${id}`),
  cancelBackfill: (id: string) =>
    request<BackfillJob>(`/v2/data/backfill/${id}/cancel`, { method: "POST" }),
  methodology: () => request<Record<string, unknown>>("/v2/methodology"),
  regime: () => request<Record<string, unknown>>("/v2/regime"),
  assistant: (releaseId: string, question: string) =>
    request<{
      mode: string;
      provider: string;
      answer: string;
      evidence_pack_hash: string;
      validation: { valid: boolean; warnings: string[] };
    }>("/v2/research/assistant", {
      method: "POST",
      body: JSON.stringify({ release_id: releaseId, question }),
    }),
};
