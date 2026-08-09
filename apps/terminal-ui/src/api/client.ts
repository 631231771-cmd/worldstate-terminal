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

const configuredBase = import.meta.env.VITE_RESEARCH_API_URL as string | undefined;
export const API_BASE = configuredBase?.replace(/\/$/, "") ?? "";

async function request<T>(
  path: string,
  init?: RequestInit,
  acceptedErrorStatuses: readonly number[] = [],
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
    if (!response.ok && !acceptedErrorStatuses.includes(response.status)) {
      const detail = await response.text();
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

const PROVIDER_NAMES: Record<string, string> = {
  fred_alfred: "FRED / ALFRED",
  bls_official: "BLS",
  federal_reserve_fomc: "Federal Reserve",
  trading_economics_consensus: "Trading Economics",
  databento_market: "Databento",
};

export const api = {
  health: () =>
    request<{
      status: string;
      version: string;
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
  dataProviders: async (): Promise<DataProvidersResponse> => {
    try {
      return await request<DataProvidersResponse>("/v2/data/providers");
    } catch {
      const legacy = await request<{
        items: Array<{
          provider_key: string;
          latest_status?: string | null;
          latest_completed_at?: string | null;
          quality_grade?: string | null;
          operations?: string[];
        }>;
      }>("/v2/providers");
      return {
        items: legacy.items.map((item) => ({
          provider_id: item.provider_key,
          display_name: PROVIDER_NAMES[item.provider_key] ?? item.provider_key,
          configured: false,
          healthy: item.latest_status === "completed" ? true : null,
          entitlement: null,
          status: "legacy_status_only",
          last_success_at: item.latest_completed_at ?? null,
          last_error: null,
          quota: null,
          data_range: null,
          quality_grade: item.quality_grade ?? null,
          next_planned_snapshot: null,
          capabilities: item.operations ?? [],
        })),
      };
    }
  },
  dataCoverage: () => request<DataCoverageResponse>("/v2/data/coverage"),
  dataFreshness: () => request<DataFreshnessResponse>("/v2/data/freshness"),
  syncPublic: (start_date: string, end_date: string) =>
    request<Record<string, unknown>>(
      "/v2/data/sync/public",
      { method: "POST", body: JSON.stringify({ start_date, end_date }) },
      [207, 424],
    ),
  bootstrapFree: () =>
    request<Record<string, unknown>>("/v2/data/bootstrap-free", { method: "POST" }, [207, 424]),
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
