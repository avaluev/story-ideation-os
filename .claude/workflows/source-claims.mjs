export const meta = {
  name: 'source-claims',
  description:
    'Per-CLAIM live evidence sourcing — the fix for low deep-link density. For every ENUMERATED external claim across the slate (not 3-5 demand points per card), a finder agent fetches a tier-1/2 primary source + a <=25-word verbatim quote, then an INDEPENDENT refute-by-default verifier confirms the quote is on the page and entails the value. Emits judgments keyed by the EXACT extractor claim_id so pipeline.veracity.merge_agent_judgments lifts SUPPORTED->VERIFIED. Never fabricates; never touches a frozen dollar figure. args = the manifest object from scripts/emit_card_claims.py: { claims: [{claim_id, card, title, claim_type, text, value, tier_hint}], chunk?, max_claims? }.',
  phases: [
    { title: 'Find', detail: 'one finder per claim (CHUNK=4) -> deep-link primary + verbatim quote' },
    { title: 'Verify', detail: 'independent refute-by-default verifier per found claim' },
  ],
}

const M = typeof args === 'string' ? JSON.parse(args) : (args || {})
const ALL = Array.isArray(M.claims) ? M.claims : []
const CHUNK = Math.min(4, Math.max(1, M.chunk || 4)) // >4 concurrent web agents trips the 429 limiter
const CLAIMS = M.max_claims ? ALL.slice(0, M.max_claims) : ALL

// Role routing (§5 reasoning sandwich). Finders are high-volume mechanical
// fetch+quote work -> Sonnet. The refute-by-default verifier does adversarial
// scope/staleness reasoning -> Opus, BUT the driver owns that choice: it gates
// on pipeline.quota and passes refuter_model:'sonnet' when Opus is exhausted, so
// the dual-survival invariant is downgraded, never skipped. Defaults keep the
// workflow runnable standalone.
const FINDER_MODEL = M.finder_model || 'sonnet'
const REFUTER_MODEL = M.refuter_model || 'opus'
const FINDER_AGENT = M.finder_agent || 'general-purpose'
const REFUTER_AGENT = M.refuter_agent || 'general-purpose'

const TIER_LADDER =
  'gov/regulator (Pew, Gallup, KFF, Census, BLS, MPA, FRED) > primary platform/trade ' +
  '(Variety, Deadline, THR, Box Office Mojo, The Numbers, Parrot Analytics, Nielsen) > ' +
  'industry archive with a deep path > aggregator (last resort, name the primary in notes)'

const FIND_SCHEMA = {
  type: 'object',
  required: ['claim_id', 'found', 'url', 'quote', 'supports', 'source_tier'],
  properties: {
    claim_id: { type: 'string', description: 'ECHO the provided claim_id UNCHANGED' },
    found: { type: 'boolean' },
    url: { type: 'string', description: 'the EXACT deep-path URL fetched (no homepage, no search query, no <url> auto-link)' },
    quote: { type: 'string', description: '<=25-word VERBATIM quote copied from the page that entails the claim value' },
    date: { type: 'string' },
    supports: { type: 'boolean', description: 'true iff the fetched page actually supports the claim value' },
    source_tier: { type: 'integer', minimum: 1, maximum: 5 },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['claim_id', 'confirms', 'refutes', 'quote_matches', 'url_is_deep'],
  properties: {
    claim_id: { type: 'string' },
    confirms: { type: 'boolean' },
    refutes: { type: 'boolean' },
    quote_matches: { type: 'boolean', description: 'the EXACT quote appears verbatim on the page' },
    url_is_deep: { type: 'boolean' },
    notes: { type: 'string' },
  },
}

function findPrompt(c) {
  return `You are an investment-research analyst sourcing ONE checkable claim for a film/series investor deck. Find a REAL primary source and prove you read it.

CLAIM (echo claim_id back UNCHANGED): ${c.claim_id}
TYPE: ${c.claim_type}
ASSERTION: ${c.text}
VALUE: ${c.value || '(see assertion)'}
CONCEPT: "${c.title}"

Do this:
1. WebSearch for the primary source, then WebFetch the DEEP-PATH page.
2. Copy a <=25-word VERBATIM quote that entails the value. Do NOT paraphrase inside the quote.
3. Prefer higher tiers: ${TIER_LADDER}.
HARD RULES (a fabricated source is total failure):
- url MUST be a deep path to the specific article/report/title page — never a homepage, never a google/bing/ddg search URL, never the <url> auto-link form.
- Set found=true and supports=true ONLY if you actually fetched the page and saw the quote support the value.
- If you cannot stand it up, set found=false (do NOT invent). One rock-solid source beats a shaky one.
- Do NOT restate, round, or alter the dollar value — you are sourcing evidence, not economics.
Return the schema; echo claim_id EXACTLY.`
}

function verifyPrompt(c, f) {
  return `You are a HOSTILE fact-checker. Assume the source does NOT support the claim until proven. Verify ONE sourced claim.

claim_id (echo back): ${c.claim_id}
VALUE asserted: ${c.value || c.text}
URL: ${f.url}
QUOTE the finder captured: "${f.quote}"

Do this: WebFetch the URL. Confirm the EXACT quote appears VERBATIM on the page AND that it entails the value (unit conversion / rounding is allowed, fabrication is not). Confirm the URL is a deep path (not a homepage/search).
Set confirms=true ONLY if all hold. Set refutes=true if the page contradicts the value. quote_matches=true ONLY if the verbatim quote is on the page. You see no finder rationale — judge only the page.
Return the schema.`
}

phase('Find')
log(`Sourcing ${CLAIMS.length} external claims, ${CHUNK} concurrent (deep-link + verbatim quote, refute-by-default verify).`)

async function chunked(items, fn) {
  const out = []
  for (let i = 0; i < items.length; i += CHUNK) {
    const batch = items.slice(i, i + CHUNK)
    log(`batch ${Math.floor(i / CHUNK) + 1}/${Math.ceil(items.length / CHUNK)} (${batch.length})`)
    const res = await parallel(batch.map((it) => () => fn(it)))
    out.push(...res)
  }
  return out
}

const found = await chunked(CLAIMS, (c) =>
  agent(findPrompt(c), {
    label: `find:${c.claim_id}`,
    phase: 'Find',
    model: FINDER_MODEL,
    agentType: FINDER_AGENT,
    schema: FIND_SCHEMA,
  })
    .then((r) => ({ ...r, _claim: c }))
    .catch(() => ({ claim_id: c.claim_id, found: false, _claim: c })),
)

const toVerify = found.filter((f) => f && f.found && f.supports && f.url && f.quote)
log(`Find done: ${toVerify.length}/${CLAIMS.length} candidates. Independent verification.`)

phase('Verify')
const verified = await chunked(toVerify, (f) =>
  agent(verifyPrompt(f._claim, f), {
    label: `verify:${f.claim_id}`,
    phase: 'Verify',
    model: REFUTER_MODEL,
    agentType: REFUTER_AGENT,
    schema: VERIFY_SCHEMA,
  })
    .then((v) => ({ f, v }))
    .catch(() => ({ f, v: { confirms: false, refutes: false, quote_matches: false } })),
)

// Build claim_id-keyed judgments for pipeline.veracity.merge_agent_judgments.
// TRUSTED iff finder found+supports AND verifier confirms+quote_matches AND not refutes.
const judgments = {}
const stillUnsourced = []
for (const c of CLAIMS) {
  const hit = verified.find((x) => x.f.claim_id === c.claim_id)
  const trusted =
    hit && hit.v.confirms && hit.v.quote_matches && !hit.v.refutes && hit.f.url_is_deep !== false
  if (trusted) {
    judgments[c.claim_id] = { supports: true, quote: hit.f.quote, url: hit.f.url, date: hit.f.date || '' }
  } else {
    stillUnsourced.push({ claim_id: c.claim_id, text: c.text, card: c.card })
  }
}

log(`Verified ${Object.keys(judgments).length}/${CLAIMS.length}; ${stillUnsourced.length} still unsourced.`)
// The caller writes judgments to JSON and runs:
//   python -m pipeline.veracity <card>.md --card --judgments <j>.json --online --assert-density 0.9
// `accounting` lets the driver attribute token burn to the right quota tier and
// call pipeline.quota.record — the workflow runtime cannot call it itself (§3 step 7).
return {
  judgments,
  still_unsourced: stillUnsourced,
  found_count: toVerify.length,
  accounting: {
    finder_model: FINDER_MODEL,
    refuter_model: REFUTER_MODEL,
    find_agents: CLAIMS.length,
    verify_agents: toVerify.length,
  },
}
