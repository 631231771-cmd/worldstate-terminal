import type { ReleaseSummary } from "./index";

export type CapabilityStatus = "AVAILABLE" | "STALE" | "MISSING";

export interface CapabilityDimension {
  available: boolean;
  status: CapabilityStatus;
  reason: string | null;
}

export interface DatasetCapability {
  dataset_key: string;
  kind: "series" | "market" | "event";
  canonical_key: string;
  label: string;
  entity: string | null;
  rows: number;
  coverage_start: string | null;
  coverage_end: string | null;
  latest_timestamp: string | null;
  latest_available_at: string | null;
  freshness: { status: string; score: number | null; reason: string | null };
  frequency: string;
  source_class: string;
  provider: string | null;
  source_url: string | null;
  data_mode: string;
  proxy: boolean;
  manual: boolean;
  fixture: boolean;
  point_in_time: boolean;
  quality_flags: string[];
  capabilities: Record<string, CapabilityDimension>;
  event_counts?: {
    actual: number;
    consensus_pre_t0: number;
    intraday_manifests: number;
    completed_analysis: number;
  };
}

export interface ProductDimension {
  key: string;
  label: string;
  score: number | null;
  direction: string;
  momentum: number | null;
  confidence: number;
  coverage: number;
  status: "available" | "missing";
  drivers: Array<{ series_key?: string; title?: string; latest_value?: number | null }>;
  details_ref: string;
}

export interface ProductMarketItem {
  key: string;
  label: string;
  symbol: string | null;
  asset_class: string;
  value: number | null;
  formatted_value: string;
  change: number | null;
  change_unit: "%" | "bp";
  direction: string;
  trend: string;
  status: "available" | "missing";
  freshness: string;
  proxy: boolean;
  derived: boolean;
  sparkline?: number[];
  chart_points?: Array<{ time: string; value: number }>;
  horizons?: Record<"1d" | "1w" | "1m" | "3m", { value: number | null; unit: "%" | "bp"; direction: string }>;
  capabilities: Record<string, CapabilityDimension>;
  details: {
    provider: string | null;
    canonical_key: string;
    data_mode: string | null;
    quality: string | null;
    limitation: string | null;
    timestamp: string | null;
    granularity_seconds: number | null;
    derivation?: { input_datasets?: string[]; formula?: string | null; calculation_version?: string | null; calculated_at?: string | null } | null;
    continuity_status?: string | null;
    continuity_segments?: Array<{ active: boolean; provider: string; source_symbol: string; interval_seconds: number; start: string; end: string; rows: number }>;
    active_segment_rows?: number | null;
  };
}

export interface ProductCountry {
  key: string;
  label: string;
  status: "available" | "partial" | "missing" | string;
  available_dimensions: string[];
  dimensions: Record<string, {
    label: string;
    score: number | null;
    direction: string;
    momentum: number | null;
    confidence: number;
    coverage: number;
    freshness: number | null;
    drivers: Array<{ series_key?: string; title?: string; latest_value?: number | null }>;
    missing: string[];
  }>;
  latest_data_at: string | null;
  details: { entity_registered?: boolean; source?: string; limitations: string[] };
}

export interface ProductTodayResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  macro_snapshot: ProductDimension[];
  markets: ProductMarketItem[];
  what_changed: Array<{
    what: string;
    why: string;
    magnitude: number | null;
    direction: string;
    confidence: number;
    category: string | null;
    category_label?: string | null;
    details_ref: string;
  }>;
  upcoming: Array<{
    id: string;
    title: string;
    release_type: string;
    period_label: string;
    scheduled_at: string;
    status: string;
  }>;
  latest_research: ReleaseSummary[];
  global: ProductCountry[];
  watch_next: string[];
  capability_summary: Record<string, number>;
  limitations: string[];
}

export interface ProductMarketsResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  items: ProductMarketItem[];
  limitations: string[];
}

export interface ProductMacroResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  countries: ProductCountry[];
  comparison: Array<{ dimension: string; countries: Array<{ iso3: string; name: string; score: number | null; direction: string }> }>;
  divergence: Array<{ dimension: string; stronger: { iso3: string; name: string; score: number }; weaker: { iso3: string; name: string; score: number }; spread: number; interpretation: string }>;
  context_cards: Array<{ key: string; title: string; status: string; components: string[] }>;
  limitations: string[];
}

export interface ProductCountryDetail {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  country: ProductCountry;
  selected_dimension: ({ key: string } & ProductCountry["dimensions"][string]) | null;
  key_series: Array<{
    key: string;
    title: string;
    dimension: string;
    dimension_label: string;
    latest_value: number | null;
    period_start: string | null;
    score: number | null;
    momentum: number | null;
    quality: string | null;
    data_mode: string;
    source_url: string | null;
  }>;
  markets: ProductMarketItem[];
  recent_releases: ReleaseSummary[];
  upcoming_releases: ReleaseSummary[];
  state_history: Array<{ date: string; value: number; direction: string | null; confidence: number | null; methodology_version: string | null }>;
  history_scope: "us_world_state" | "unavailable" | string;
  comparisons: Array<{ country_key: string; country_label: string; score: number; direction: string; coverage: number }>;
  limitations: string[];
}

export interface ProductEventsResponse {
  as_of: string;
  data_mode: string;
  methodology_version: string;
  items: ReleaseSummary[];
  upcoming: ReleaseSummary[];
  recent: ReleaseSummary[];
  default_event_id: string | null;
  limitations: string[];
}

export interface ProductSupportedIndicator {
  key: string;
  label: string;
  unit: string;
  family: string;
  hotter_when_higher: boolean;
}

export interface ProductEventDetail {
  event: {
    id: string;
    release_key: string;
    type: string;
    title: string;
    country: string;
    period_label: string;
    scheduled_at: string;
    released_at: string | null;
    source_timezone: string;
    status: string;
    data_mode: string;
  };
  supported_indicators: ProductSupportedIndicator[];
  expectations: {
    available: boolean;
    eligible_count: number;
    rule: string;
    indicators: Array<ProductSupportedIndicator & {
      consensus: number | null;
      captured_at: string | null;
      source: string | null;
      snapshot_id: string | null;
      eligibility: "pre_t0" | "missing";
    }>;
  };
  actual: {
    available: boolean;
    indicators: Array<ProductSupportedIndicator & {
      actual: number | null;
      previous: number | null;
      revised_previous: number | null;
      revision: number | null;
      source: string | null;
      release_value_id: string | null;
    }>;
  };
  surprise: {
    available: boolean;
    classification: string | null;
    score: number | null;
    direction: string | null;
    methodology: string | null;
    indicators: Array<ProductSupportedIndicator & {
      available: boolean;
      raw_surprise: number | null;
      relative_surprise: number | null;
      surprise_z: number | null;
      threshold_scaled_surprise: number | null;
      direction: string | null;
      sample_count: number | null;
      z_score_unavailable_reason?: string | null;
    }>;
  };
  market_reaction: {
    status: "available" | "partial" | "missing";
    available: boolean;
    available_assets: EventReactionAsset[];
    partial_assets: EventReactionAsset[];
    missing_assets: EventReactionAsset[];
    required_granularity_seconds: number;
    limitations: string[];
    matrix: Array<{
      stage_key: string;
      instrument_key: string;
      instrument_label: string;
      symbol: string;
      is_proxy: boolean;
      windows: Record<string, { value: number | null; unit: "%" | "bp"; direction: string; coverage: number | null; reversal: boolean; missing_reason: string | null }>;
    }>;
    analysis_run_id: string | null;
  };
  historical_context: Record<string, unknown>;
  analysis: {
    run_id: string | null;
    status: string;
    reproducibility: string | null;
    confidence: number | null;
    data_gaps: string[];
  };
  actions: {
    can_add_consensus: boolean;
    can_import_consensus_csv: boolean;
    can_import_minutes: boolean;
    can_run_analysis: boolean;
    analysis_blockers: string[];
  };
  stages: Array<Record<string, unknown>>;
  contamination: Record<string, unknown>;
  source: Record<string, unknown> | null;
  data_provenance: Record<string, unknown>;
  data_quality: Array<Record<string, unknown>>;
  id: string;
  values: Record<string, Record<string, unknown>>;
  bundle: Record<string, unknown>;
  latest_analysis: Record<string, unknown> | null;
}

export interface EventReactionAsset {
  key: string;
  label: string;
  symbol: string | null;
  status?: string;
  eligible?: boolean;
  row_count?: number;
  quality?: string;
  is_proxy: boolean;
  proxy_for: string | null;
}

export interface ConsensusCsvPreview {
  release_id: string;
  t0: string;
  supported_indicators: ProductSupportedIndicator[];
  items: Array<{
    row: number;
    indicator_key: string;
    indicator_label: string;
    consensus_value: string;
    captured_at: string;
    source_name: string;
    source_url: string | null;
    status: "eligible" | "post_t0" | "unknown_indicator" | "invalid";
    eligible: boolean;
    reason: string | null;
  }>;
  summary: { eligible: number; post_t0: number; unknown_indicator: number; invalid: number; total: number };
  can_confirm: boolean;
}

export interface EventMinutePreview {
  release_id: string;
  instrument: EventReactionAsset;
  t0: string;
  timezone: string;
  eligibility: {
    status: "eligible" | "partial" | "ineligible";
    eligible: boolean;
    reasons: string[];
    limitations: string[];
    bar_count: number;
    first_timestamp: string;
    last_timestamp: string;
    nearest_t0_seconds: number;
    pre_event_minutes: number;
    post_event_minutes: number;
    missing_bar_count: number;
    duplicate_count: number;
    one_minute_interval_ratio: number;
    granularity_seconds: number;
    data_mode: string;
    is_fixture: boolean;
    manual: boolean;
    verified: boolean;
  };
  preview: Array<{ timestamp: string; open: string; high: string; low: string; close: string; volume: string | null }>;
  parse_errors: string[];
  warnings: string[];
}
