export type MacroDataMode = 'LIVE' | 'STALE' | 'DEMO' | 'EMPTY';

export interface MacroDriver {
  canonical_key: string;
  title: string;
  score: number;
  value: number;
  raw_value: number;
  as_of: string;
  contribution: number;
  transform: string;
}

export interface MacroState {
  key: string;
  score: number | null;
  label: string;
  confidence: number;
  trend: 'rising' | 'falling' | 'stable';
  top_drivers: MacroDriver[];
  missing_series: string[];
  stale: boolean;
  as_of: string | null;
  experimental: boolean;
}

export interface MacroChange {
  type: string;
  title: string;
  explanation: string;
  previous: unknown;
  current: unknown;
  date: string;
  state: string | null;
  importance: number;
  source: string;
}

export interface MacroSystemStatus {
  mode: MacroDataMode;
  database: 'sqlite' | 'postgresql';
  observations: number;
  series: number;
  last_sync_at: string | null;
  syncing: boolean;
  fred_configured: boolean;
  warnings: string[];
}

export interface MacroSnapshot {
  generated_at: string;
  mode: MacroDataMode;
  methodology_version: string;
  states: MacroState[];
  top_changes: MacroChange[];
  regime: {
    growth: number | null;
    inflation: number | null;
    confidence: number;
    trajectory: Array<{ date: string; growth: number; inflation: number }>;
  };
  releases: Array<{
    title: string;
    scheduled_at: string;
    importance: number;
    source: string;
  }>;
  system: MacroSystemStatus;
}

export interface MacroSeriesSummary {
  canonical_key: string;
  native_id: string;
  title: string;
  frequency: string;
  unit: string;
  default_transform: string;
  source_url: string;
  source_mode: 'live' | 'demo' | null;
}

export interface MacroSeriesDetail extends MacroSeriesSummary {
  transform: string;
  last_updated: string | null;
  revision_count: number;
  observations: Array<{
    date: string;
    raw: number | null;
    value: number | null;
    percentile: number | null;
    vintage_date: string;
  }>;
}

export type WorldEvidenceMode = 'LIVE' | 'PARTIAL' | 'OFFLINE';
export type TutorMode = 'beginner' | 'deep' | 'socratic';

export interface WorldEvent {
  id: string;
  rank: number;
  title: string;
  display_title: string;
  summary: string;
  source: string;
  url: string;
  published_at: string | null;
  category: string;
  language: string;
  importance: number;
  event_type: string;
  core_question: string;
  why_it_matters: string;
  expectation_shift: string;
  causal_chain: string[];
  chain_labels: string[];
  assets: string[];
  concept: string;
  scenario: string;
  expected_moves: Partial<Record<string, 'up' | 'down'>>;
  market_thesis: string;
  confirmations: string[];
  falsifiers: string[];
  alternatives: string[];
  learning_prompt: string;
  learning_answer: string;
  confidence: number;
  analysis_type: 'evidence_based_hypothesis';
}

export interface WorldMarket {
  key: string;
  name_zh: string;
  name_en: string;
  symbol: string;
  unit: string;
  region: string;
  available: boolean;
  price?: number;
  previous_close?: number;
  change_percent?: number;
  as_of?: string;
  source?: string;
  source_url?: string;
  sparkline?: number[];
  direction: 'up' | 'down' | 'flat' | 'unavailable';
  role: string;
  question: string;
  explanation: string;
  evidence: string[];
  confidence: number;
  order_flow_known?: boolean;
}

export interface WorldBriefing {
  generated_at: string;
  as_of_timezone: string;
  evidence_mode: WorldEvidenceMode;
  headline: string;
  mission: string;
  events: WorldEvent[];
  markets: WorldMarket[];
  lead_validation: {
    event_id?: string;
    scenario?: string;
    status: string;
    label: string;
    summary: string;
    supports?: number;
    weakens?: number;
    rows: Array<{
      market_key: string;
      market_name: string;
      role: string;
      expected: 'up' | 'down';
      expected_label: string;
      observed: WorldMarket['direction'];
      observed_label: string;
      status: 'supports' | 'weakens' | 'unclear';
    }>;
    timing_note?: string;
  };
  lesson: {
    concept: string;
    question: string;
    simple: string;
    deep: string;
    check_question: string;
    worked_example: string[];
    retrieval_answer: string;
    transfer_question: string;
  };
  upcoming: Array<{
    title: string;
    scheduled_at: string;
    importance: number;
    source: string;
  }>;
  macro_context: {
    mode: MacroDataMode;
    methodology_version: string;
    states: Array<{
      key: string;
      score: number | null;
      label: string;
      confidence: number;
    }>;
  };
  ai: {
    provider: string;
    model: string;
    available: boolean;
    grounding: string;
  };
  sources: {
    news: string[];
    markets: string[];
    macro: string[];
  };
  limitations: string[];
}

export interface TutorAnswer {
  generated_at: string;
  answer: string;
  provider: string;
  model: string;
  mode: TutorMode;
  grounded: boolean;
  citations: Array<{ title: string; url: string; source: string }>;
  warning: string | null;
  disclaimer: string;
}

export interface TutorMessage {
  role: 'user' | 'assistant';
  content: string;
}

const DEFAULT_API_URL = 'http://127.0.0.1:8000';
const SNAPSHOT_CACHE_MS = 5_000;

function configuredApiUrl(): string {
  const buildUrl = import.meta.env.VITE_MACRO_ENGINE_URL;
  if (typeof buildUrl === 'string' && buildUrl.trim()) return buildUrl.replace(/\/$/, '');
  try {
    const stored = localStorage.getItem('worldstate-macro-engine-url');
    if (stored) return stored.replace(/\/$/, '');
  } catch {
    // Local storage is optional; desktop defaults remain available.
  }
  return DEFAULT_API_URL;
}

export class MacroApiError extends Error {
  constructor(
    message: string,
    public readonly offline: boolean,
    public readonly status?: number,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${configuredApiUrl()}${path}`, {
      headers: { Accept: 'application/json' },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new MacroApiError('Macro Engine is offline', true);
  }
  if (!response.ok) {
    throw new MacroApiError(`Macro Engine returned HTTP ${response.status}`, false, response.status);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${configuredApiUrl()}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new MacroApiError('Macro Engine is offline', true);
  }
  if (!response.ok) {
    throw new MacroApiError(`Macro Engine returned HTTP ${response.status}`, false, response.status);
  }
  return response.json() as Promise<T>;
}

let snapshotCache: { at: number; value: MacroSnapshot } | null = null;
let snapshotRequest: Promise<MacroSnapshot> | null = null;

export async function getMacroSnapshot(
  options: { signal?: AbortSignal; fresh?: boolean } = {},
): Promise<MacroSnapshot> {
  if (!options.fresh && snapshotCache && Date.now() - snapshotCache.at < SNAPSHOT_CACHE_MS) {
    return snapshotCache.value;
  }
  if (!snapshotRequest) {
    snapshotRequest = getJson<MacroSnapshot>('/v1/snapshot', options.signal)
      .then((value) => {
        snapshotCache = { at: Date.now(), value };
        window.dispatchEvent(new CustomEvent('worldstate:snapshot', { detail: value }));
        return value;
      })
      .finally(() => {
        snapshotRequest = null;
      });
  }
  return snapshotRequest;
}

export function getMacroSeries(signal?: AbortSignal): Promise<MacroSeriesSummary[]> {
  return getJson<MacroSeriesSummary[]>('/v1/series', signal);
}

export function getMacroSeriesDetail(
  canonicalKey: string,
  transform: string,
  signal?: AbortSignal,
): Promise<MacroSeriesDetail> {
  const path = `/v1/series/${encodeURIComponent(canonicalKey)}?transform=${encodeURIComponent(transform)}`;
  return getJson<MacroSeriesDetail>(path, signal);
}

export function getMacroApiUrl(): string {
  return configuredApiUrl();
}

export function getWorldBriefing(
  options: { signal?: AbortSignal; fresh?: boolean } = {},
): Promise<WorldBriefing> {
  const query = options.fresh ? '?fresh=true' : '';
  return getJson<WorldBriefing>(`/v1/world/briefing${query}`, options.signal);
}

export function askWorldTutor(
  question: string,
  mode: TutorMode,
  history: TutorMessage[],
  signal?: AbortSignal,
): Promise<TutorAnswer> {
  return postJson<TutorAnswer>(
    '/v1/world/ask',
    {
      question,
      mode,
      history: history.slice(-8),
    },
    signal,
  );
}
