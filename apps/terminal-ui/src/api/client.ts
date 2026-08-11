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
import type { ConsensusCsvPreview, DatasetCapability, EventMinutePreview, ProductCountryDetail, ProductEventDetail, ProductEventsResponse, ProductMacroResponse, ProductMarketsResponse, ProductTodayResponse } from "../types/product";

const configuredBase = import.meta.env.VITE_RESEARCH_API_URL as string | undefined;
export const API_BASE = configuredBase?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  readonly status: number | null;
  readonly technicalDetail: string;

  constructor(message: string, status: number | null, technicalDetail = message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.technicalDetail = technicalDetail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  acceptedErrorStatuses: readonly number[] = [],
  timeoutMs = 15_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}${path}`, {
        ...init,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...init?.headers },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiError("Data request timed out. Try again.", null, error.message);
      }
      throw new ApiError("Research service is unavailable. Check that WorldState is running.", null, error instanceof Error ? error.message : String(error));
    }
    if (!response.ok && !acceptedErrorStatuses.includes(response.status)) {
      const raw = await response.text();
      let detail = raw;
      try {
        const parsed = JSON.parse(raw) as { detail?: string };
        detail = parsed.detail ?? raw;
      } catch {
        // Keep the raw body as technical detail when it is not JSON.
      }
      const userMessage = response.status >= 500
        ? "The research service returned an error. Open Data Sources for diagnostics."
        : response.status === 404
          ? "This research view is not available in the current service version."
          : detail || `Request failed (${response.status})`;
      throw new ApiError(userMessage, response.status, detail || `HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
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
  productToday: (dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<ProductTodayResponse>(`/v2/product/today?data_mode=${dataMode}`, undefined, [], 45_000),
  productMarkets: (dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<ProductMarketsResponse>(`/v2/product/markets?data_mode=${dataMode}`, undefined, [], 45_000),
  productMacro: (dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<ProductMacroResponse>(`/v2/product/macro?data_mode=${dataMode}`, undefined, [], 45_000),
  productCountry: (country: string, dimension?: string, dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<ProductCountryDetail>(`/v2/product/macro/${encodeURIComponent(country)}?data_mode=${dataMode}${dimension ? `&dimension=${encodeURIComponent(dimension)}` : ""}`, undefined, [], 45_000),
  productEvents: (dataMode: "observed" | "fixture" | "all" = "observed", limit = 500) =>
    request<ProductEventsResponse>(`/v2/product/events?data_mode=${dataMode}&limit=${limit}`, undefined, [], 45_000),
  productEvent: (id: string, dataMode: "observed" | "fixture" | "all" = "observed") =>
    request<ProductEventDetail>(`/v2/product/events/${encodeURIComponent(id)}?data_mode=${dataMode}`, undefined, [], 45_000),
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
