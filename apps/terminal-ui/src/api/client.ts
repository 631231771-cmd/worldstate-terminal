import type {
  ExplanationsResponse,
  HistoricalResponse,
  Instrument,
  ReleaseDetail,
  ReleaseSummary,
  TimelineResponse,
  WindowsResponse,
} from "../types";

const configuredBase = import.meta.env.VITE_RESEARCH_API_URL as string | undefined;
export const API_BASE = configuredBase?.replace(/\/$/, "") ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `HTTP ${response.status}`);
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
  releases: () => request<ReleaseSummary[]>("/v2/releases?limit=500"),
  release: (id: string) => request<ReleaseDetail>(`/v2/releases/${id}`),
  windows: (id: string) => request<WindowsResponse>(`/v2/releases/${id}/windows`),
  timeline: (id: string) => request<TimelineResponse>(`/v2/releases/${id}/timeline`),
  historical: (id: string) =>
    request<HistoricalResponse>(`/v2/releases/${id}/historical-matches`),
  explanations: (id: string) =>
    request<ExplanationsResponse>(`/v2/releases/${id}/explanations`),
  instruments: () => request<Instrument[]>("/v2/instruments"),
  dataQuality: () => request<Record<string, unknown>>("/v2/data-quality"),
  providerRuns: () => request<Array<Record<string, unknown>>>("/v2/provider-runs"),
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
