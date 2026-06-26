// Reusable cost-guardrail predicates for workflow fan-outs.
//
// veracity-amplify.mjs had NO aggregate agent cap, NO budget abort, NO quota
// gate (verified by grep: no MAX_AGENT/abort/quota/kill). Running a hundreds-of-
// agents fan-out without a ceiling is the "unsupervised cost blowup" the
// NEXT_SESSION_PLAYBOOK risk table warns about. These are the missing guards.
//
// They are PURE functions so a plain `node` test can prove they fire
// (_wf_guardrails.test.mjs) -- the Workflow sandbox forbids Date.now()/Math.random
// (a wall-clock kill therefore lives at the orchestrator, not in-script), so the
// in-script ceiling is: a hard MAX_AGENTS cap + a token-budget abort + a quota
// pre-check passed in via args. amplify-quality.mjs inlines this same logic
// (the Workflow runtime does not assume cross-file ESM import).

/** True once the lifetime agent count reaches the cap. */
export function capReached(dispatched, maxAgents) {
  return dispatched >= maxAgents
}

/**
 * True when the remaining token budget has fallen below `reserveFrac` of the
 * target. Inactive (always false) when no budget target was set (budgetTotal
 * falsy) -- the cap is then the sole ceiling.
 */
export function budgetExhausted(budgetTotal, budgetRemaining, reserveFrac = 0.2) {
  if (!budgetTotal) return false
  return budgetRemaining < budgetTotal * reserveFrac
}

/** True when the orchestrator's ADR-0008 quota gate refused before launch. */
export function quotaRefused(quotaOk) {
  return quotaOk === false
}

/**
 * Combined gate used before each chunk. Returns {ok, reason}. `ok=false` means
 * STOP dispatching and emit a partial manifest (partial-with-provenance beats
 * blown-budget-with-nothing).
 */
export function chunkGate({ dispatched, maxAgents, budgetTotal, budgetRemaining, quotaOk, reserveFrac = 0.2 }) {
  if (quotaRefused(quotaOk)) return { ok: false, reason: 'quota gate refused (weekly headroom)' }
  if (capReached(dispatched, maxAgents)) return { ok: false, reason: `MAX_AGENTS cap ${maxAgents} reached` }
  if (budgetExhausted(budgetTotal, budgetRemaining, reserveFrac))
    return { ok: false, reason: `token budget headroom < ${reserveFrac * 100}%` }
  return { ok: true, reason: '' }
}
