# Stabilization Cycle — Operator Playbook (STAB-01)

The stabilization cycle is a short feedback loop run after every pipeline pass
to catch quality degradation before it compounds. There are two failure modes:
genuine slop that sneaked past the anti-slop eval, and false positives that
wrongly ban a valid asset class. The cycle handles both deterministically.

---

## Step 1 — Detect

Run `make eval` or `make audit` after a pipeline pass. The eval suite runs
`evals/test_anti_slop.py` (slop pattern coverage), `evals/test_quality.py`
(critic score distribution), and the concept audit (`pipeline audit-concepts`).

A stabilization action is triggered when any of the following are true:

- An eval check fails (non-zero exit from `make eval`)
- Critic scores drop more than 5 points from the prior run's median
- `make audit` flags a concept with `SLOP_DETECTED` in its quality block
- An operator manually notices a concept with a clichéd pattern

---

## Step 2 — Diagnose

Read the flagged concept in `out/concepts/<run-id>/` and the failing eval
output. Determine the root cause:

**Genuine slop** — the concept contains a pattern that the engine should
never produce: underdog-sports-team-redemption arc, chosen-one prophecy,
misunderstood-genius narrative, or any other pattern already documented in
`docs/adr/` as prohibited. The pattern is real, recurring, and generalisable.

**False positive** — the concept superficially resembles a banned pattern but
is substantively different. The asset is historically real, the psychological
need is documented, and the TRIZ contradiction is non-trivial. The eval check
is triggering on surface-level language rather than structural similarity.

The distinction is decisive: getting it wrong in either direction costs real
output quality.

---

## Step 3 — Act

**If genuine slop:** propose the new banned term or phrase and open it for
operator review. Do NOT edit `prompts/anti_slop.md` directly from an automated
session — the STAB-02 hook (`pre_anti_slop_gate.py`) will block any Write or
Edit to that file and require explicit operator approval. Submit the proposed
addition, wait for the operator to approve and commit it manually.

**If false positive:** do NOT add anything to `prompts/anti_slop.md`. Instead:

1. Save the flagged concept to `examples/rejected/` with a `reason.md`
   explaining why the eval misfired.
2. If the concept is actually strong, promote it to `examples/golden/` with
   an annotation explaining what makes it legitimate despite surface similarity
   to a banned pattern.
3. Consider whether the eval check itself needs refinement (open a separate
   ticket; do not patch the eval unilaterally).

---

## Step 4 — Verify

After any change (new ban added, or false-positive documented):

1. Re-run `make eval` to confirm the targeted pattern is now caught (for
   genuine slop) or the false-positive rate has not increased (for false
   positives).
2. Confirm the worked example lands in the right directory
   (`examples/rejected/` or `examples/golden/`).
3. Commit with a message that references the STAB cycle:
   ```
   fix(stab): ban <pattern-name> pattern in anti_slop.md
   docs(stab): add <concept-name> as golden false-positive example
   ```
4. Update `docs/stabilization-cycle.md` if the playbook needs refinement
   based on what you learned.

---

## Worked Example: 1920s Women's Boxing League

**Trigger:** Concept `out/concepts/run-0042/concept-017.json` — "The Iron Lace
Circuit" — flagged by `evals/test_anti_slop.py` under the check
`underdog_sports_redemption`. The concept concerns a fictional women's boxing
circuit in 1920s Chicago.

**Step 1 — Detect:** `make eval` exits non-zero; the anti-slop eval reports
`SLOP_DETECTED` with match token `"underdog sports"`.

**Step 2 — Diagnose:** Operator reads the concept. The psychological need is
`SDT: autonomy + relatedness` for women barred from professional sport by
Illinois statute (1923). The asset is the documented Riverview Park gymnasium
records (a real archive). The TRIZ contradiction is `#35: parameter change`
— the fighters change weight classes mid-bout as a legal loophole, not a
training arc. The "underdog sports" token matched on the word "underdog" in
the concept's logline, not on the structural pattern. **Verdict: false positive.**

**Step 3 — Act:** The concept is NOT added to `prompts/anti_slop.md`. The
concept JSON is copied to `examples/golden/iron-lace-circuit/` with
`reason.md` explaining:

> The anti-slop eval matched on the word "underdog" in the logline. The
> structural pattern is not a redemption arc — it is a legal arbitrage story
> driven by a documented historical constraint. The banned pattern targets
> narratives where the protagonist succeeds through effort and belief; this
> concept succeeds through rule exploitation. Do not ban "underdog" as a
> standalone token.

**Step 4 — Verify:** `make eval` is re-run. The golden example is added to
the eval's allow-list for this specific concept ID. Exit 0. Commit:

```
docs(stab): add iron-lace-circuit as golden false-positive example (STAB-01)
```

---

## Reference

- STAB-02: the PreToolUse hook (`pre_anti_slop_gate.py`) that forces human
  review of any edit to `prompts/anti_slop.md`.
- MEM-12: the durability reference (`docs/durability.md`) for the guarantees
  the system makes about state persistence across pipeline runs.
- ADR-0002: LLMs must not do arithmetic; scoring.py is the only score source.
