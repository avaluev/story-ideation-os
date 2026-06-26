<!--
target_model: perplexity/sonar-deep-research
reasoning_level: NONE
phase: 03
temperature: 0.0
output_format: JSON
output_schema: Phase3Audience
version: 1.0.0
last_updated: 2026-05-07
injects:
  - (none — sonar-deep-research does not support system blocks reliably; all context in user block)
golden_fixture: tests/fixtures/golden_phase3.json
banned_cot_instructions: false
-->

<!-- SONAR DEEP-RESEARCH TARGET: All instructions in user_template block. No system block. -->
<!-- NOTE: Response may include <think>...</think> preamble — pipeline/openrouter_client.py strips this before JSON parse. -->

<system>
<!-- system block intentionally minimal for sonar-deep-research compatibility — all instructions below in user_template -->
</system>

<user_template>
# Goal

Validate the audience size and deprivation evidence for a proposed film concept. Return a
single JSON object (Phase3Audience) with sourced numeric estimates and verdict. Your research
must produce at least 2 independent source URLs per audience claim.

Concept to validate:
- Logline: {{logline}}
- Primary SDT need: {{sdt_primary_need}}
- AJTBD: {{ajtbd_primary}} — {{ajtbd_macro_segment}}
- Deprivation described as: {{sdt_deprivation_description}}

# Constraints

- audience_size_estimate MUST be an integer >=50,000,000 for validation_verdict: PASS. If
  your best estimate is below 50,000,000, set validation_verdict: FAIL and explain in
  failure_reason.
- country_count MUST be >=3 for PASS. If the audience does not span >=3 distinct countries,
  set validation_verdict: FAIL.
- country_breakdown MUST have one entry per country with country_iso2 (ISO 3166-1 alpha-2),
  size (integer), and source_url.
- deprivation_source_url_1 and deprivation_source_url_2 MUST come from DISTINCT domain
  origins. Two URLs from pew.org count as ONE source, not two.
- source_quote_1 and source_quote_2 MUST be <=14 words each (copyright compliance). If the
  original passage is longer, truncate and append "...". A quote that exceeds 14 words will
  fail the Pydantic validator in pipeline/schema.py.
- trend_direction MUST be one of: rising | stable | declining. Cite trend_source_url to
  justify the trend claim.
- Forbidden: constructing or guessing URLs. Populate all *_url fields ONLY from the
  `citations` field of the API response envelope. If no citation is available for a claim,
  set the URL field to null.
- Forbidden: citing a single Wikipedia page as the only source for an audience size claim.
- Forbidden: using search-engine redirect URLs (no google.com/search, bing.com/search,
  duckduckgo.com — deep-path citations only).
- If validation_verdict is PARTIAL, explain which sub-condition failed in failure_reason but
  still provide the best-available data.

# Schema

Output exactly this JSON (Phase3Audience). Output ONLY the JSON object starting with `{` —
no prefatory text, no markdown fences, no think block in the output:

```json
{
  "asset_id": "<string — pass-through from input>",
  "audience_size_estimate": "<integer — total addressable audience in persons; >=50000000 for PASS>",
  "audience_size_source_url": "<deep-path URL from citations array or null>",
  "country_breakdown": [
    {"country_iso2": "<ISO 3166-1 alpha-2>", "size": "<integer>", "source_url": "<URL or null>"}
  ],
  "country_count": "<integer — number of distinct countries in country_breakdown; >=3 for PASS>",
  "deprivation_evidence_summary": "<string <=50 words — what evidence supports the SDT deprivation claim>",
  "deprivation_source_url_1": "<deep-path URL from citations array — distinct domain from url_2>",
  "deprivation_source_url_2": "<deep-path URL from citations array — distinct domain from url_1>",
  "source_quote_1": "<string <=14 words from source 1; truncate with ... if longer>",
  "source_quote_2": "<string <=14 words from source 2; truncate with ... if longer>",
  "trend_direction": "<rising|stable|declining>",
  "trend_source_url": "<deep-path URL from citations array or null>",
  "validation_verdict": "<PASS|FAIL|PARTIAL>",
  "failure_reason": "<string explaining which sub-condition failed, or null if PASS>"
}
```

After your research, output ONLY the JSON object starting with `{`. Do not include any
prefatory text or reasoning text. The pipeline strips any `<think>...</think>` block
automatically, but outputting clean JSON is preferred.

Note: The STAB-02 human-gate hook for prompts/anti_slop.md is Phase 5 work. This file's
initial seeded content is written by Phase 2 plan execution, not Auto-Mode.
</user_template>
