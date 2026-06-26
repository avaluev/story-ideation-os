export const meta = {
  name: 'veracity-amplify',
  description: 'Reality-verify every claim in a generated slate against a primary source (deep-link + verbatim quote) and amplify the weak ones — producing per-claim judgments a deterministic Python scorer folds into a credibility grade.',
  phases: [
    { title: 'Verify', detail: 'one agent per claim: fetch source, confirm the number, capture a direct quote + deep-link; search a primary source if the cited one is dead' },
    { title: 'Amplify', detail: 'one agent per weak/gap claim: find a stronger primary source or raise a defensible TAM' },
  ],
}

// args: { claims_file: "runs/veracity/claims_to_verify.json", count: N }
// Each agent self-loads its single claim by INDEX (proven enrich pattern), so the
// workflow args stay tiny and this scales to hundreds of claims.
const A = (typeof args === 'string') ? JSON.parse(args) : (args || {})
const FILE = A.claims_file
const COUNT = A.count || 0
if (!FILE || !COUNT) { log('veracity-amplify: need {claims_file, count}'); return { judgments: {} } }
log(`veracity-amplify: ${COUNT} claims from ${FILE}`)

const CHUNK = 4  // >4 concurrent web agents trips the provider 429 limiter
const idxs = Array.from({ length: COUNT }, (_, i) => i)
const loadCmd = (i) => `python3 -c "import json;print(json.dumps(json.load(open('${FILE}'))[${i}]))"`

const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['claim_id', 'supports', 'refutes', 'value_found', 'quote', 'verified_url', 'source_tier', 'http_note', 'notes'],
  properties: {
    claim_id: { type: 'string' },
    supports: { type: ['boolean', 'null'] },
    refutes: { type: 'boolean' },
    value_found: { type: 'string' },
    quote: { type: 'string' },
    verified_url: { type: 'string' },
    source_tier: { type: 'integer', minimum: 1, maximum: 5 },
    http_note: { type: 'string', enum: ['reachable', 'bot-block', 'dead', 'replaced'] },
    notes: { type: 'string' },
  },
}

const AMPLIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['claim_id', 'found', 'better_url', 'better_stat', 'quote', 'source_tier', 'rationale'],
  properties: {
    claim_id: { type: 'string' },
    found: { type: 'boolean' },
    better_url: { type: 'string' },
    better_stat: { type: 'string' },
    quote: { type: 'string' },
    source_tier: { type: 'integer', minimum: 1, maximum: 5 },
    rationale: { type: 'string' },
  },
}

function verifyPrompt(i) {
  return [
    `You are a forensic fact-checker for an investor-grade film pitch. Verify ONE claim against a primary source. Return ONLY the JSON object.`,
    ``,
    `STEP 0 — load your claim (run this Bash command and read the printed JSON):`,
    `  ${loadCmd(i)}`,
    `It gives: claim_id, claim_type, text (the assertion), value (the figure to confirm), cited_url.`,
    ``,
    `STEP 1 — WebFetch cited_url; look for the value (allow rounding/unit conversion: 758,539,785 supports $758.5M).`,
    `STEP 2 — if present: supports=true; copy a VERBATIM <=25-word quote from the page that contains/entails it; verified_url=the deep link.`,
    `STEP 3 — if the page loads but the figure differs: supports=false; put what you found in value_found.`,
    `         If it is an allow-listed paywall/bot-block primary (Variety/Deadline/Box Office Mojo/SEC/Pew/etc.): supports=null, http_note="bot-block", then try STEP 4.`,
    `STEP 4 — if dead/missing/contradicts: WebSearch for a PRIMARY source (gov > platform/API > trade press) that confirms it; if found return its DEEP-PATH url + a verbatim quote with supports=true; else supports=false, verified_url="".`,
    ``,
    `HARD RULES: deep links only (no google/bing/duckduckgo, no bare domains, no <url> auto-link). NEVER fabricate a URL, quote, or number. Echo claim_id unchanged. refutes=true ONLY if the source actively contradicts the value.`,
  ].join('\n')
}

function amplifyPrompt(i) {
  return [
    `Find the STRONGEST defensible primary source for ONE claim (close a gap or tier up). Return ONLY the JSON object.`,
    ``,
    `STEP 0 — load your claim (run this Bash command and read the printed JSON):`,
    `  ${loadCmd(i)}`,
    `If claim_type is "market_tam": find the LARGEST market figure a NAMED report actually states for this format/genre (global SVOD/theatrical content spend, format CAGR) — verbatim, no extrapolation.`,
    `Otherwise: find a higher-tier primary source confirming the value (government/regulatory > platform/API > Box Office Mojo/The Numbers > trade press).`,
    ``,
    `Open the source with WebFetch. Return a DEEP-PATH https url + the figure VERBATIM from that page + a <=30-word quote. NEVER inflate beyond what the source says. Nothing defensible -> found=false. Echo claim_id.`,
  ].join('\n')
}

async function runChunked(todo, fn, collect, passLabel) {
  for (let i = 0; i < todo.length; i += CHUNK) {
    const r = await parallel(todo.slice(i, i + CHUNK).map(x => () => fn(x)))
    for (const item of r) { if (item) collect(item) }
    log(`${passLabel} ${Math.min(i + CHUNK, todo.length)}/${todo.length}`)
  }
}

// ---- Phase 1: Verify ----------------------------------------------------- //
phase('Verify')
const verifyByIdx = {}  // index -> verify result (carries echoed claim_id)
const verifyOne = (i) => agent(verifyPrompt(i), {
  schema: VERIFY_SCHEMA, agentType: 'general-purpose', label: `verify:${i}`, phase: 'Verify',
}).then(v => (v ? { i, v } : null)).catch(() => null)
await runChunked(idxs, verifyOne, (x) => { verifyByIdx[x.i] = x.v }, 'verify')
const missed = idxs.filter(i => !verifyByIdx[i])
if (missed.length) { log(`verify retry ${missed.length}`); await runChunked(missed, verifyOne, (x) => { verifyByIdx[x.i] = x.v }, 'verify-retry') }

// ---- Phase 2: Amplify weak/gap ------------------------------------------ //
phase('Amplify')
const amplifyByIdx = {}
const weakIdx = idxs.filter(i => { const v = verifyByIdx[i]; return !v || v.supports !== true })
const amplifyOne = (i) => agent(amplifyPrompt(i), {
  schema: AMPLIFY_SCHEMA, agentType: 'general-purpose', label: `amplify:${i}`, phase: 'Amplify',
}).then(a => (a ? { i, a } : null)).catch(() => null)
await runChunked(weakIdx, amplifyOne, (x) => { amplifyByIdx[x.i] = x.a }, 'amplify')

// ---- Merge into per-claim judgments (keyed by the echoed claim_id) ------- //
const judgments = {}
for (const i of idxs) {
  const v = verifyByIdx[i]
  if (!v || !v.claim_id) continue
  const amp = amplifyByIdx[i]
  const supports = v.supports === true ? true : (v.supports === false ? false : null)
  judgments[v.claim_id] = {
    supports,
    refutes: !!v.refutes,
    quote: v.quote || (amp && amp.found ? amp.quote : ''),
    verified_url: v.verified_url || (amp && amp.found ? amp.better_url : ''),
    amplify: amp || null,
  }
}
const nVerified = Object.values(judgments).filter(j => j.supports === true).length
const nAmplified = Object.values(amplifyByIdx).filter(a => a && a.found).length
log(`veracity-amplify: ${nVerified}/${COUNT} verified · ${nAmplified} amplified`)
return { judgments, stats: { total: COUNT, verified: nVerified, amplified: nAmplified } }
