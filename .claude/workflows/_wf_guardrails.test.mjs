// Proof the cost guardrails actually fire (NEXT_SESSION_PLAYBOOK Phase 3b).
// Run: node .claude/workflows/_wf_guardrails.test.mjs
import assert from 'node:assert/strict'
import { capReached, budgetExhausted, quotaRefused, chunkGate } from './_wf_guardrails.mjs'

// --- MAX_AGENTS cap ---
assert.equal(capReached(119, 120), false)
assert.equal(capReached(120, 120), true)
assert.equal(capReached(121, 120), true)

// --- token-budget abort (inactive when no target set) ---
assert.equal(budgetExhausted(null, 0), false, 'no target -> inactive')
assert.equal(budgetExhausted(1_000_000, 300_000), false, '30% remaining -> ok')
assert.equal(budgetExhausted(1_000_000, 150_000), true, '15% remaining -> abort')
assert.equal(budgetExhausted(1_000_000, 200_000), false, 'exactly 20% -> ok (strict <)')

// --- quota pre-check ---
assert.equal(quotaRefused(false), true)
assert.equal(quotaRefused(true), false)
assert.equal(quotaRefused(undefined), false)

// --- combined chunk gate: each guard independently stops the batch ---
assert.equal(chunkGate({ dispatched: 0, maxAgents: 120, quotaOk: true }).ok, true)
assert.equal(chunkGate({ dispatched: 0, maxAgents: 120, quotaOk: false }).ok, false)
assert.equal(chunkGate({ dispatched: 120, maxAgents: 120, quotaOk: true }).ok, false)
assert.equal(
  chunkGate({ dispatched: 0, maxAgents: 120, quotaOk: true, budgetTotal: 1e6, budgetRemaining: 1e5 }).ok,
  false,
)

console.log('OK: cap / budget / quota guardrails all fire as specified.')
