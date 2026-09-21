import type { AuthorClaim, MechanismAssessment, ReasoningCase, ReasoningPlaybook, ResearchSource } from "../types/reasoning";
import { request } from "./transport";

export const reasoningApi = {
  reasoningPlaybooks: () => request<{ items: ReasoningPlaybook[]; policy: string }>("/v2/reasoning/playbooks"),
  reasoningCases: () => request<ReasoningCase[]>("/v2/reasoning/cases?data_mode=observed"),
  createResearchSource: (payload: {
    title: string;
    author: string;
    source_type: string;
    source_url?: string;
    content_text: string;
    notes?: string;
  }) => request<ResearchSource>("/v2/reasoning/sources", {
    method: "POST",
    body: JSON.stringify({ ...payload, data_mode: "observed" }),
  }),
  extractAuthorClaim: (sourceId: string, payload: {
    statement: string;
    exact_quote: string;
    extraction_method: "manual" | "ai";
    extractor_model?: string;
  }) => request<AuthorClaim>(`/v2/reasoning/sources/${encodeURIComponent(sourceId)}/claims`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  reviewAuthorClaim: (claimId: string, payload: {
    decision: "confirmed" | "rejected";
    mechanism_key?: string;
    review_notes?: string;
  }) => request<AuthorClaim>(`/v2/reasoning/claims/${encodeURIComponent(claimId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  assessAuthorClaim: (claimId: string) => request<MechanismAssessment>(
    `/v2/reasoning/claims/${encodeURIComponent(claimId)}/assessments`,
    { method: "POST", body: JSON.stringify({}) },
    [],
    60_000,
  ),
};
