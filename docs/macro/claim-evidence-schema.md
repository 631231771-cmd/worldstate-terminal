# Claim and evidence schema

An `EvidenceItem` is registered before a report claim can cite it. A claim has
a type, statement, evidence IDs, confidence, inference flag, limitations and a
falsifier. Confirmed facts require evidence; inferences require an explicit
inference flag and limitations or falsifier. Fixture and proxy evidence must be
disclosed. Every cited and contradicting ID must exist in the current run,
confirmed facts cannot be evidence-free, historical claims require historical
evidence, and inference requires both limitations and a falsifier. Unsupported
or numerically inconsistent evidence fails validation. Invalid AI-shaped output
is rejected in favour of deterministic, evidence-bound claims.
