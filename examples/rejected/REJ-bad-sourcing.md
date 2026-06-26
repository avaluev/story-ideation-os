---
concept_id: REJ-bad-sourcing
status: rejected
failure_mode: sourcing_failure
failing_checks: ["sources_per_claim_lt_2", "bare_domain_citation"]
---

# REJ-bad-sourcing

## Logline

A community of undocumented Somali refugees rebuilds their neighborhood after a
flood, despite sustained local government opposition — and when a teenage girl
discovers that the only path to flood insurance requires exposing the community's
status, she must choose between her neighbors' safety and their secrecy.

## Why This Failed

**Failure mode:** Sourcing failure. The concept has structural merit — there is
a TRIZ contradiction (getting insurance requires disclosure; disclosure creates
deportation risk; the more insurance obtained, the more visible the community
becomes to enforcement), a clear irreversible moment (the first insurance
application creates a paper trail), and a universal JTBD (help me protect people
I love without destroying what I am protecting them from). The concept fails
solely on citation grounds.

**Failing checks:**

- `sources_per_claim_lt_2`: The audience claim — "50 million Somali diaspora
  globally" — cannot be supported by two distinct-domain URLs with deep paths.
  UNHCR tracks Somali displacement; the actual documented Somali diaspora is
  approximately 1.5–2 million people. The 50-million claim is not supportable
  because it is incorrect. A corrected audience claim (Somali diaspora + East
  African diaspora + Muslim-majority audiences in Europe who identify with
  displacement themes) would need to be reconstructed from multiple sources and
  would likely produce a real TAM of 20–35 million — still below the 50M floor.

- `bare_domain_citation`: During concept drafting, the audience sourcing
  referenced unhcr.org without a deep-path URL (no `/refugee-statistics/` or
  specific report URL included). A bare domain is not a citation — it is a
  pointer to an organization. The Anomaly Engine's citation eval requires a URL
  with a path that identifies the specific document or dataset being cited. The
  bare domain reference fails the `_is_bare_domain` check in scripts/audit.py.

**Why the premise cannot be rescued as drafted:** Two problems compound each
other. First, the audience claim is factually wrong (50M Somali diaspora does
not exist; the real number is ~2M). Correcting it reveals the second problem:
even with the East African diaspora and European Muslim audience combined, the
concept may not reach 50M. The TRIZ architecture is sound and worth preserving
for a concept with a larger confirmed audience.

**Correct sourcing practice (for future reference):** An audience claim of this
type requires: (1) a UNHCR URL with the specific report and table cited, e.g.,
https://www.unhcr.org/refugee-statistics/insights/explainers/somali-displacement.html;
(2) a second distinct-domain URL from a government statistical agency or academic
source confirming the figure from a different methodology. If two distinct-domain
deep-path URLs cannot be found, the audience_size field must be set to null and
the concept flagged for human review.

**Stabilization lesson:** Build the citation before building the concept. If the
audience claim requires a number you cannot immediately source to two distinct
deep-path URLs, the concept is not ready for the pipeline. Unsourced audience
claims are not conservative estimates — they are fabrications, and they corrupt
the downstream scoring that the entire pipeline depends on. The Anomaly Engine's
value proposition is that every number traces to evidence. A concept with a
fabricated audience claim is not an Anomaly Engine concept.
