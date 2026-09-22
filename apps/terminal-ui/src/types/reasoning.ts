export type EvidenceState = "supporting" | "contradicting" | "neutral" | "missing" | "mixed";

export interface ReasoningMechanismSummary {
  key: string;
  title: string;
  summary: string;
  chain: string[];
  falsifiers: string[];
  limitations: string[];
  competing_mechanisms: string[];
}

export interface ReasoningPlaybook {
  playbook_key: string;
  version: string;
  title: string;
  source_framework: string;
  description: string;
  hash: string;
  mechanisms: ReasoningMechanismSummary[];
}

export interface ResearchSource {
  id: string;
  title: string;
  author: string;
  source_type: string;
  source_url: string | null;
  published_at: string | null;
  retrieved_at: string;
  content_text: string;
  content_hash: string;
  notes: string;
  provenance: Record<string, unknown>;
  data_mode: "observed" | "fixture";
  created_at: string;
  updated_at: string;
}

export interface EvidenceCheck {
  role?: "directional" | "risk" | "context";
  source_url?: string | null;
  point_in_time?: boolean;
  limitation?: string;
  sample_count?: number;
  rule_key: string;
  label: string;
  state: EvidenceState;
  statement: string;
  evidence_ids: string[];
  missing_reason?: string | null;
  instrument_key?: string;
  dimension?: string;
  observed_value?: number | null;
  unit?: string;
  observed_at?: string | null;
  provider?: string | null;
  proxy?: boolean;
}

export interface MechanismStepAssessment {
  key: string;
  label: string;
  mechanism: string;
  state: EvidenceState;
  checks: EvidenceCheck[];
}

export interface MechanismEvaluation {
  key: string;
  title: string;
  summary: string;
  status: "insufficient_data" | "mixed" | "contradicted" | "supported" | "incomplete" | "unconfirmed";
  system_assessment: string;
  chain_progress: {
    supported_through: number;
    total_steps: number;
    supporting_steps: number;
    contradicting_steps: number;
    missing_steps: number;
  };
  steps: MechanismStepAssessment[];
  falsifiers: string[];
  limitations: string[];
}

export interface MechanismAssessment {
  id: string;
  claim_id: string;
  playbook_key: string;
  playbook_version: string;
  playbook_hash: string;
  primary_mechanism_key: string;
  as_of: string;
  evaluated_at: string;
  data_mode: string;
  input_snapshot_hash: string;
  output_hash: string;
  result: {
    author_claim: {
      statement: string;
      exact_quote: string;
      author: string;
      source_title: string;
      source_url: string | null;
    };
    system_assessment: {
      primary_mechanism_key: string;
      as_of: string;
      data_mode: string;
      mechanisms: MechanismEvaluation[];
      truthfulness_note: string;
    };
  };
}

export interface AuthorClaim {
  id: string;
  source_id: string;
  statement: string;
  exact_quote: string;
  extraction_method: "manual" | "ai";
  extractor_model: string | null;
  status: "draft" | "confirmed" | "rejected";
  mechanism_key: string | null;
  mechanism_version: string | null;
  confirmed_at: string | null;
  confirmed_by: string | null;
  review_notes: string;
  data_mode: string;
  created_at: string;
  updated_at: string;
  latest_assessment: MechanismAssessment | null;
}

export interface ReasoningCase {
  source: ResearchSource;
  claims: AuthorClaim[];
}
