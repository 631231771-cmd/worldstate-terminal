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
  history?: Array<{ date: string; close: number }>;
  horizons?: {
    one_day: number | null;
    five_day: number | null;
    twenty_day: number | null;
  };
  direction: 'up' | 'down' | 'flat' | 'unavailable';
  role: string;
  question: string;
  explanation: string;
  evidence: string[];
  confidence: number;
  order_flow_known?: boolean;
}

export interface WorldPerspective {
  id: string;
  title: string;
  claim: string;
  source: string;
  source_class: 'institutional' | 'researcher' | 'practitioner' | 'social' | string;
  source_class_label: string;
  url: string;
  published_at: string | null;
  lens: string;
  translation: string;
  test_with: string[];
  caveat: string;
  channel?: 'public_feed' | 'official_x_api' | 'agent_reach_x' | string;
  author?: string | null;
  account_class?: 'official' | 'institutional' | 'researcher' | 'practitioner' | string | null;
  research_role?: string | null;
  engagement?: number | null;
  views?: number | null;
  relevance_score: number;
  relevance_label: '直接相关' | '机制相关' | '背景观察' | string;
  relevance_reason: string;
  related_event_ids: string[];
}

export interface WorldCalendarEvent {
  id: string;
  title: string;
  scheduled_at: string;
  country: string;
  kind: 'policy' | 'inflation' | 'labor' | 'growth' | 'trade' | 'income' | 'macro' | string;
  impact: 'high' | 'medium' | string;
  source: string;
  source_url: string;
  retrieval: 'live_official' | 'bundled_official_schedule' | 'local_macro_snapshot' | string;
  time_precision: 'minute' | 'date' | string;
  question: string;
  scenario_hotter: string;
  scenario_softer: string;
  watch_assets: string[];
}

export interface WorldCalendarStatus {
  state: string;
  connected: boolean;
  sources_attempted: number;
  sources_succeeded: number;
  items: number;
  horizon_days: number | null;
  checked_at: string;
  cache: {
    hit: boolean;
    ttl_seconds: number;
    fetched_at: string | null;
    age_seconds?: number;
  };
  calls: Array<{
    source: string;
    status: string;
    items: number;
    duration_ms: number;
    reason?: string;
  }>;
}

export interface WorldEventReaction {
  event_id: string | null;
  state: 'released' | 'upcoming' | 'waiting' | string;
  state_label: string;
  title: string;
  scheduled_at: string | null;
  country?: string;
  kind?: string;
  impact?: string;
  source?: string;
  source_url?: string;
  window_label: string;
  values: {
    actual: string | number | null;
    forecast: string | number | null;
    previous: string | number | null;
    status: 'not_verified' | 'awaiting_release' | 'unavailable' | string;
    note: string;
  };
  steps: Array<{
    key: 'fact' | 'surprise' | 'variables' | 'assets' | 'amplifiers' | 'verify' | string;
    number: string;
    title: string;
    state: 'observed' | 'prepared' | 'waiting' | 'hypothesis' | 'active' | string;
    summary: string;
  }>;
  pricing_variables: Array<{
    market_key: string;
    name: string;
    move: number | null;
    direction: WorldMarket['direction'];
    reading: string;
  }>;
  asset_reactions: Array<{
    market_key: string;
    name: string;
    move: number | null;
    direction: WorldMarket['direction'];
    role: string;
    channel: string;
    verdict: string;
    evidence_state: 'observed_daily' | 'unavailable' | string;
  }>;
  shared_move_note: string;
  amplifiers: string[];
  verdict: {
    label: string;
    summary: string;
    confidence: number;
    confidence_label: string;
  };
  next_checks: string[];
  caveats: string[];
}

export interface WorldMarketSystem {
  breadth: {
    up: number;
    down: number;
    flat: number;
    available: number;
  };
  regimes: Array<{
    key: string;
    title: string;
    score: number;
    label: string;
    summary: string;
    evidence: string[];
    confidence: number;
    method: string;
  }>;
  patterns: Array<{
    title: string;
    state: string;
    explanation: string;
    markets: string[];
    confidence: number;
  }>;
  correlations: Array<{
    left: string;
    right: string;
    label: string;
    correlation: number | null;
    observations: number;
    interpretation: string;
  }>;
  horizons: Array<{
    key: string;
    name: string;
    one_day: number | null;
    five_day: number | null;
    twenty_day: number | null;
  }>;
  method: string;
}

export interface WorldTopic {
  key: string;
  title: string;
  question: string;
  strength: number;
  state: 'dominant' | 'active' | 'monitor' | 'quiet' | string;
  label: string;
  event_ids: string[];
  event_count: number;
  perspective_ids: string[];
  perspective_count: number;
  market_keys: string[];
  market_moves: Array<{ key: string; change_percent: number | null }>;
  why_now: string;
}

export interface WorldCountry {
  code: string;
  name: string;
  flag: string;
  question: string;
  attention: number;
  event_count: number;
  event_ids: string[];
  market_keys: string[];
  market_moves: Array<{ key: string; change_percent: number | null }>;
  lead: string;
}

export interface WorldEventArchetype {
  key: string;
  title: string;
  trigger: string;
  first_markets: string[];
  path: string;
  failure: string;
  event_types: string[];
  active: boolean;
  related_event_id: string | null;
}

export interface WorldPipelineModule {
  key: string;
  title: string;
  state: string;
  attempted: number;
  succeeded: number;
  items: number;
  detail: string;
}

export interface WorldDeepBrief {
  editorial_model: string;
  read_time: string;
  question: string;
  bottom_line: string;
  sections: Array<{
    key: 'fact' | 'mechanism' | 'evidence' | 'debate' | 'watch';
    title: string;
    label: string;
    body: string;
    detail?: string;
    evidence?: Array<{
      market: string;
      role: string;
      observed: string;
      verdict: 'supports' | 'weakens' | 'unclear';
    }>;
    perspectives?: Array<{
      source: string;
      class: string;
      claim: string;
      lens: string;
      caveat: string;
      url: string;
    }>;
    watch?: string[];
  }>;
  external_editions: Array<{
    id: string;
    type: string;
    content: string;
    created_at: string | null;
    url: string;
  }>;
  edition_rule: string;
}

export interface WorldCourseModule {
  id: string;
  number: string;
  title: string;
  level: string;
  duration: string;
  question: string;
  outcomes: string[];
  resources: Array<{
    title: string;
    url: string;
    provider: string;
    access: string;
  }>;
}

export interface WorldBriefing {
  generated_at: string;
  as_of_timezone: string;
  evidence_mode: WorldEvidenceMode;
  headline: string;
  mission: string;
  events: WorldEvent[];
  markets: WorldMarket[];
  market_system: WorldMarketSystem;
  calendar: {
    events: WorldCalendarEvent[];
    status: WorldCalendarStatus;
    method: string;
  };
  event_reaction: WorldEventReaction;
  topics: WorldTopic[];
  countries: WorldCountry[];
  event_archetypes: WorldEventArchetype[];
  desk: {
    event_count: number;
    market_coverage: string;
    source_count: number;
    next_high_impact: WorldCalendarEvent | null;
    active_topics: string[];
    top_country: WorldCountry | null;
    question: string;
  };
  research_pipeline: WorldPipelineModule[];
  macro_chain: {
    title: string;
    scenario: string;
    current_stage: string;
    stages: Array<{
      key: string;
      number: string;
      title: string;
      horizon: string;
      state: string;
      summary: string;
      watch: string[];
    }>;
    feedback_loop: string;
    method: string;
  };
  deep_brief: WorldDeepBrief;
  perspectives: WorldPerspective[];
  curriculum: WorldCourseModule[];
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
  upcoming: WorldCalendarEvent[];
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
    perspectives: string[];
    markets: string[];
    macro: string[];
  };
  integrations: {
    x: {
      configured: boolean;
      mode: 'official_api' | 'not_configured';
      items: number;
      credential_storage: 'backend_environment_only';
    };
    agent_reach_x: {
      enabled: boolean;
      configured: boolean;
      connected: boolean;
      state:
        | 'connected'
        | 'unavailable'
        | 'disabled'
        | 'cli_missing'
        | 'credentials_missing'
        | 'not_checked'
        | string;
      backend: 'agent_reach_twitter_cli';
      mode: 'local_cookie_read_only';
      credential_storage: 'local_config_to_child_process_only';
      executable_available: boolean;
      accounts: number;
      calls_attempted: number;
      calls_succeeded: number;
      items: number;
      checked_at: string;
      cache: {
        hit: boolean;
        ttl_seconds: number;
        fetched_at: string | null;
        age_seconds?: number;
      };
      calls: Array<{
        handle: string;
        label: string;
        account_class: string;
        research_role: string;
        status: 'ok' | 'failed' | 'timeout' | string;
        items: number;
        duration_ms: number;
        latest_at: string | null;
        reason?: string;
      }>;
    };
    official_calendar: WorldCalendarStatus;
    clawfeed: {
      configured: boolean;
      connected: boolean;
      editions: number;
      mode: 'external' | 'built_in_editorial';
      checked_at: string;
      principle: string;
    };
    webmcp: {
      mode: 'progressive_enhancement';
      tools: string[];
    };
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
