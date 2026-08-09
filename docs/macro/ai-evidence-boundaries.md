# AI evidence boundaries

AI sits last in the pipeline and receives an `EvidencePack`, not raw social
media, unrestricted web search or an empty prompt. The pack contains:

- confirmed release and market facts;
- source references and quality labels;
- historical statistics and sample restrictions;
- rule-generated primary and competing hypotheses;
- contamination, confidence and explicit gaps.

The validator rejects unsupported numbers, absent instruments, unlabelled
causal certainty and claims that contradict the pack. The report must distinguish
“observed”, “historically associated”, “most consistent with”, “competing
explanation” and “cannot confirm”.

An external model is optional. Without one, the deterministic structured report
remains usable. AI failure cannot block ingestion, event-window calculation or
historical comparison.
