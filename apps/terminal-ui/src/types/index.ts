export type ViewKey = "today" | "world-state" | "markets" | "releases" | "event-lab" | "cross-asset" | "series" | "countries" | "research" | "data-methods";

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
  reproducibility_status?: string | null;
  analysis_completed_at?: string | null;
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
    raw_surprise: number | null;
    oriented_surprise: number | null;
    relative_surprise: number | null;
    threshold_scaled_surprise: number | null;
    surprise_z: number | null;
    direction: string;
    revision: number | null;
    history_sample_count: number;
    history_mean: number | null;
    history_std: number | null;
    history_cutoff_at: string | null;
    surprise_method: string;
    z_score_unavailable_reason: string | null;
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
  data_mode?: "observed" | "fixture" | "manual" | string;
  bundle: {
    classification: string;
    score: number | null;
    direction: string;
    reasons: string[];
    revision_dominant: boolean;
    revision_analysis?: Record<string, unknown>;
    composite_method?: string;
    component_methods?: Record<string, string>;
    minimum_z_score_sample?: number;
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
    input_snapshot_hash?: string | null;
    config_hash?: string | null;
    market_dataset_hash?: string | null;
    historical_sample_hash?: string | null;
    output_hash?: string | null;
    reproducibility_status?: string;
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
  data_provenance?: ReleaseDataProvenance | null;
  data_quality: DataQuality[];
}

export interface ProvenanceSource {
  provider_key?: string;
  display_name?: string;
  source_name?: string;
  source_url?: string | null;
  artifact_id?: string | null;
  snapshot_id?: string | null;
  captured_at?: string | null;
  retrieved_at?: string | null;
  content_hash?: string | null;
  quality_grade?: string | null;
}

export interface MarketDatasetProvenance {
  provider_key?: string;
  dataset?: string;
  schema?: string;
  manifest_hash?: string | null;
  range_start?: string | null;
  range_end?: string | null;
  granularity?: string | null;
}

export interface ContractProvenance {
  instrument_key: string;
  instrument_title?: string;
  symbol?: string;
  contract_code?: string | null;
  provider_symbol?: string | null;
  instrument_id?: string | null;
  dataset?: string | null;
  expiry?: string | null;
  first_notice?: string | null;
  last_trade?: string | null;
  roll_status?: string | null;
  selection_rule?: string | null;
}

export interface ReleaseDataProvenance {
  official_source?: ProvenanceSource | string | null;
  consensus_source?: ProvenanceSource | string | null;
  consensus_captured_at?: string | null;
  market_dataset?: MarketDatasetProvenance | string | null;
  contracts?: ContractProvenance[];
  data_mode?: "observed" | "fixture" | "manual" | string;
  reconciled?: boolean | null;
  reconciliation_status?: string | null;
  reconciliation_notes?: string[];
  reconciliation_summary?: {
    expected_subject_count: number;
    covered_subject_count: number;
    comparison_record_count?: number;
    missing_subject_ids: string[];
    partial_comparisons_are_complete: boolean;
  } | null;
  data_gaps?: string[];
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
  dataset?: string | null;
  contract_code?: string | null;
  quality_grade: string;
  missing_reason: string | null;
  calendar_name?: string;
  calendar_precision?: string;
  expected_tradable_bars?: number;
  experimental?: boolean;
  limitations?: string[];
  manifest_ids?: string[];
  schema_name?: string | null;
  futures_contract_id?: string | null;
}

export interface ResearchClaim {
  claim_id: string;
  claim_type: string;
  statement: string;
  evidence_ids: string[];
  confidence: number;
  is_inference: boolean;
  limitations: string[];
  falsifier: string | null;
  validation: { valid: boolean };
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
  analysis_run_id: string | null;
  facts: Array<Record<string, unknown> | string>;
  explanations: Explanation[];
  confidence: number;
  data_gaps: string[];
  report: string;
  report_validation: Record<string, unknown>;
}

export interface HistoricalResponse {
  release_id: string;
  analysis_run_id: string | null;
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

export interface ProviderQuota {
  used: number | null;
  limit: number | null;
  remaining: number | null;
  period: string | null;
  resets_at?: string | null;
}

export interface ProviderDataRange {
  start: string | null;
  end: string | null;
}

export interface DataProviderStatus {
  provider_id: string;
  display_name: string;
  configured: boolean;
  healthy: boolean | null;
  entitlement: string | null;
  status: string;
  last_success_at: string | null;
  last_error: string | null;
  quota: ProviderQuota | null;
  data_range: ProviderDataRange | null;
  quality_grade: string | null;
  next_planned_snapshot?: string | null;
  capabilities: string[];
}

export interface DataProvidersResponse {
  items: DataProviderStatus[];
  checked_at?: string | null;
  data_mode?: string;
}

export interface CoverageDimension {
  status: string;
  mode?: string | null;
  data_mode?: string | null;
  quality?: string | null;
  quality_grade?: string | null;
  available?: boolean;
  stored?: boolean;
  analysis_eligible?: boolean;
  record_count?: number;
  stored_record_count?: number;
  analysis_eligible_record_count?: number;
  stored_item_count?: number | null;
  last_updated_at?: string | null;
  missing_reason?: string | null;
  eligibility_reason?: string | null;
}

export interface DataCoverageRow {
  event_type: string;
  title?: string;
  actual: CoverageDimension;
  consensus: CoverageDimension;
  intraday: CoverageDimension;
  daily: CoverageDimension;
  source_quality: string | CoverageDimension | null;
  source_quality_basis?: {
    assessed_record_count: number;
    grades: string[];
    ungraded_eligible_actuals: number;
  };
}

export interface DataCoverageResponse {
  items: DataCoverageRow[];
  as_of?: string | null;
  data_mode?: string;
  observed_only?: boolean;
}

export interface BackfillRequest {
  start_date: string;
  end_date: string;
  event_types: string[];
  assets: string[];
}

export interface BackfillDatasetEstimate {
  dataset: string;
  assets?: string[];
  estimated_records?: number | null;
  estimated_bytes?: number | null;
  estimated_cost_usd?: number | null;
}

export interface BackfillEstimate {
  estimate_id?: string | null;
  start_date: string;
  end_date: string;
  event_count: number;
  asset_count: number;
  datasets: BackfillDatasetEstimate[];
  minute_range?: string;
  pre_minutes?: number;
  post_minutes?: number;
  estimated_records: number;
  estimated_bytes: number;
  estimated_cost_usd: number;
  budget_limit_usd: number | null;
  allow_execute: boolean;
  already_available_records?: number;
  records_to_download?: number;
  blocked_reason?: string | null;
  provider_status?: string | null;
}

export interface BackfillJob {
  id: string;
  status: string;
  progress_percent: number;
  current_stage?: string | null;
  events_total?: number;
  events_completed?: number;
  downloaded_records?: number;
  skipped_records?: number;
  failed_records?: number;
  estimated_cost_usd?: number | null;
  actual_cost_usd?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  last_error?: string | null;
  can_cancel?: boolean;
}

export interface WorldStateDimension {
  score: number | null;
  direction: string;
  momentum: number | null;
  confidence: number;
  coverage: number;
  freshness: number | null;
  top_drivers: Array<{
    series_key: string;
    title: string;
    score: number;
    momentum: number;
    latest_value: number | null;
    period_start: string | null;
    provider: string;
    source_url: string;
    data_mode: string;
    quality: string;
    evidence_ids: string[];
  }>;
  missing_inputs: string[];
}

export interface WorldStateResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  dimensions: Record<string, WorldStateDimension>;
  regime: { label: string; tags: string[]; confidence: number };
  limitations: string[];
}

export interface DailyBriefResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  world_state: WorldStateResponse;
  biggest_changes: Array<{
    what_changed: string;
    magnitude: number;
    why_it_matters: string;
    related_state: string;
    evidence: string[];
    source: string | null;
    timestamp: string | null;
    confidence: number;
    category: string;
    data_mode: string;
  }>;
  macro_events: ReleaseSummary[];
  market_confirmation: Array<Record<string, unknown>>;
  revisions: Array<Record<string, unknown>>;
  upcoming: ReleaseSummary[];
  watch_next: string[];
  ai_note: string;
  limitations: string[];
}
