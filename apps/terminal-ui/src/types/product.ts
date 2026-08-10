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
  sparkline?: number[];
  capabilities: Record<string, CapabilityDimension>;
  details: {
    provider: string | null;
    canonical_key: string;
    data_mode: string | null;
    quality: string | null;
    limitation: string | null;
    timestamp: string | null;
    granularity_seconds: number | null;
  };
}

export interface ProductCountry {
  key: string;
  label: string;
  status: "available" | "partial" | "missing" | string;
  available_dimensions: string[];
  dimensions: Record<string, {
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
