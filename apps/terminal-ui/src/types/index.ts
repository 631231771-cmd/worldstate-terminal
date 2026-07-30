export type ViewKey = "today" | "releases" | "event-lab" | "cross-asset" | "data-methods";

export interface ReleaseSummary {
  id: string;
  release_key: string;
  release_type: "US_CPI" | "US_NFP" | "FOMC" | string;
  title: string;
  period_label: string;
  scheduled_at: string;
  released_at: string | null;
  status: string;
  classification: string | null;
  surprise_score: number | null;
  confidence: number | null;
  analysis_status: string;
  data_mode: string;
  clean_window: boolean;
  contamination_level: string;
}

export interface ReleaseValue {
  indicator_id: string;
  name: string;
  unit: string;
  actual: number | null;
  consensus: number | null;
  previous: number | null;
  revised_previous: number | null;
  consensus_source: string | null;
  consensus_captured_at: string | null;
  surprise?: {
    raw: number | null;
    relative: number | null;
    standardized: number | null;
    direction: string;
    revision: number | null;
    history_samples: number;
  };
}

export interface ReleaseDetail {
  id: string;
  release_key: string;
  release_type: string;
  title: string;
  country: string;
  period_label: string;
  scheduled_at: string;
  released_at: string | null;
  source_timezone: string;
  status: string;
  data_version: string;
  bundle: {
    classification: string;
    score: number | null;
    direction: string;
    reasons: string[];
    revision_dominant: boolean;
    methodology_version: string;
  };
  values: Record<string, ReleaseValue>;
  stages: Array<{
    id: string;
    key: string;
    title: string;
    sequence: number;
    scheduled_at: string;
    released_at: string | null;
    status: string;
  }>;
  contamination: {
    level: string;
    clean_window: boolean;
    overlapping_events: Array<Record<string, unknown>>;
    confounding_notes: string[];
    causal_language: string;
  };
  latest_analysis: {
    id: string;
    status: string;
    confidence: number;
    started_at: string;
    completed_at: string | null;
    code_version: string;
    data_gaps: string[];
  } | null;
  source: {
    id: string;
    title: string;
    url: string;
    provider_key: string;
    retrieved_at: string;
    content_hash: string;
    is_fixture: boolean;
    citation: string;
  } | null;
  data_quality: DataQuality[];
}

export interface WindowResult {
  stage_key: string;
  stage_title: string;
  instrument_key: string;
  instrument_title: string;
  symbol: string;
  is_proxy: boolean;
  proxy_for: string | null;
  window_key: string;
  window_label: string;
  return_percent: number | null;
  change_basis_points: number | null;
  max_up_percent: number | null;
  max_down_percent: number | null;
  realized_volatility: number | null;
  volume_change_percent: number | null;
  coverage_ratio: number;
  direction: string;
  spike_fade: boolean;
  dip_recovery: boolean;
  direction_reversal: boolean;
  granularity_seconds: number;
  provider_key: string;
  quality_grade: string;
  missing_reason: string | null;
}

export interface Reaction {
  stage_key: string;
  instrument_key: string;
  instrument_title: string;
  earliest_significant_at: string | null;
  latency_seconds: number | null;
  initial_direction: string;
  reaction_strength: number;
  lead_rank: number | null;
  direction_reversal: boolean;
  limitations: string[];
}

export interface WindowsResponse {
  release_id: string;
  analysis_run_id: string | null;
  items: WindowResult[];
  reactions: Reaction[];
}

export interface TimelinePoint {
  timestamp: string;
  value: number;
  normalized_percent: number | null;
  volume: number | null;
}

export interface TimelineResponse {
  release_id: string;
  stages: Array<{ key: string; title: string; timestamp: string }>;
  series: Record<
    string,
    {
      title: string;
      symbol: string;
      is_proxy: boolean;
      proxy_for: string | null;
      points: TimelinePoint[];
    }
  >;
  granularity_seconds: number;
  limitation: string;
}

export interface Explanation {
  kind: string;
  title: string;
  summary: string;
  confidence: number;
  causal_language: string;
  mechanism_steps: string[];
  confirming_evidence: Array<string | Record<string, unknown>>;
  contradicting_evidence: Array<string | Record<string, unknown>>;
  unresolved: Array<string | Record<string, unknown>>;
  rule_key: string;
}

export interface ExplanationsResponse {
  release_id: string;
  analysis_run_id: string;
  facts: Array<Record<string, unknown> | string>;
  explanations: Explanation[];
  confidence: number;
  data_gaps: string[];
  report: string;
  report_validation: Record<string, unknown>;
}

export interface HistoricalResponse {
  release_id: string;
  analysis_run_id: string;
  mode: string;
  reliability: string;
  pre_filter_count: number;
  post_filter_count: number;
  filters: Array<{ condition: string; before: number; after: number }>;
  metrics: Record<string, Record<string, unknown>>;
  similar_cases: Array<Record<string, unknown>>;
  warning: string | null;
}

export interface DataQuality {
  id?: string;
  subject_type?: string;
  source_name: string;
  source_url?: string | null;
  source_type?: string;
  acquired_at?: string;
  is_manual: boolean;
  is_verified: boolean;
  is_fixture: boolean;
  is_proxy: boolean;
  latency_seconds?: number | null;
  granularity_seconds?: number | null;
  missing_reason?: string | null;
  quality_grade: string;
  verification_notes?: string | null;
}

export interface Instrument {
  id: string;
  key: string;
  symbol: string;
  title: string;
  asset_class: string;
  instrument_type: string;
  exchange: string | null;
  quote_unit: string;
  measurement_type: string;
  is_proxy: boolean;
  proxy_for: string | null;
}
