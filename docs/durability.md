# Durability Reference (MEM-12)

Internal operator reference. This document describes what the Anomaly Engine
pipeline guarantees about state durability — and what it does not guarantee.
It is not marketing copy.

---

## What We Guarantee

### Atomic Writes

`pipeline/state.py::safe_write` implements write atomicity via the standard
tmp-file pattern: the new content is written to a `.tmp` sibling file, flushed
to the OS buffer (`file.flush()`), synced to disk (`os.fsync()`), and then
renamed over the target path (`os.replace()`). On POSIX systems `os.replace()`
is guaranteed atomic at the filesystem level. At no point is a partial or
zero-byte version of the target file observable by a reader.

### Per-Boundary Checkpoints

Each pipeline phase boundary writes a checkpoint to `data/0X_<phase>.jsonl`
before advancing. A `kill -9` between two phase boundaries loses at most the
in-progress phase; all prior phases are recoverable from their JSONL files
without re-running the upstream LLM calls.

This is the ADR-0001 guarantee: all cross-boundary state must be file-persisted
before the phase is declared done.

### Deterministic Replay

On the same seed (`--seed N`), re-running a phase from a checkpoint produces
byte-identical output within `produced_at` timestamp tolerance. This holds
because:

- Asset mining and JTBD mapping are deterministic at temperature 0 (or seeded
  temperature for the phases that require it).
- Scoring (`pipeline/scoring.py`) is pure Python with no randomness.
- The Forge phase (Phase 4) uses `--seed` to fix the LLM sampling sequence;
  the same seed + same model + same prompt = same tokens.

### Recovery Eval

`evals/test_resume.py` (MEM-09) is the CI proof of the replay guarantee. It
runs a full pipeline pass, kills the process mid-Phase-4, resumes from the
checkpoint, and asserts byte-identical concept output. This eval must be green
before any "done" declaration. The Stop hook (`stop_verify.py`) blocks session
close if RESUME.md is stale relative to `data/run_log.jsonl`.

---

## What We Do Not Guarantee

Literal 100% durability is unreachable; we deliver atomic writes + per-boundary checkpoints + deterministic replay on same seed + recovery eval (MEM-09).

The specific gaps:

**OS-level fsync lies.** Some filesystems (notably ext3 in `data=writeback`
mode, some NFS mounts, and APFS under heavy load) acknowledge `fsync()` before
the write is physically on disk. A power failure in the window between
`fsync()` acknowledgement and actual disk commit can corrupt the `.tmp` file.
`os.replace()` will never make a corrupted `.tmp` visible, but the checkpoint
may be incomplete or zero-byte after a hard power failure on such filesystems.

**Parent directory sync gap.** `os.replace()` atomically renames the file
entry but does not `fsync()` the parent directory inode. On a power failure
between the rename and the next parent-directory sync, the new filename may
disappear from the directory listing even though the data is on disk. This is
OS-dependent and rare on modern Linux kernels with journaled filesystems, but
not eliminated.

**Network filesystems and Docker volumes.** NFS, SMB, and Docker bind mounts
without `O_SYNC` semantics do not provide POSIX atomicity guarantees for
`os.replace()`. Do not run the pipeline against a checkpoint directory on a
network filesystem unless you accept the risk of corrupted checkpoints.

**Python interpreter crashes.** A segfault or out-of-memory kill inside the
Python interpreter during `safe_write` may corrupt the `.tmp` file. If this
happens, the target file is unchanged (the rename never ran), but the in-flight
concept is lost. `safe_write` mitigates this with `unlink(missing_ok=True)` in
the exception handler, so the `.tmp` file is cleaned up on the next run.

---

## Known Limitations

### Phase 4 (GoT Forge) Partial Output Risk

Phase 4 is the highest-risk phase for partial output because it fans out across
multiple OpenRouter calls (K=3 or K=8 per concept). Each concept is
JSONL-flushed via `append_jsonl` on completion. A `kill -9` between two
concepts within a single Phase 4 iteration may drop the in-progress concept;
all previously flushed concepts are safe. The recovery eval (MEM-09) tests
resumption from the mid-Phase-4 sentinel; it does NOT test a kill mid-concept.

### Recovery Eval Scope

`evals/test_resume.py` (MEM-09) tests for byte-identical output on the same
seed after a mid-phase kill. It does NOT test power-off scenarios, NFS mounts,
or Docker volume edge cases. The eval is a correctness proof for the happy
path, not a disaster recovery certification.

---

## Implementation References

- `pipeline/state.py::safe_write` — the atomic write implementation.
- `evals/test_resume.py` — the MEM-09 recovery eval.
- ADR-0001 (`docs/adr/0001-jsonl-not-memory.md`) — the state durability
  architectural decision record.
