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

