# Fixture: high-ambiguity task

Step 3 Tier-2 verification input (docs/implementation/step-03-refiner-designer.md). A raw task
description with at least two structurally different, equally-plausible readings, each of which
would produce a materially different spec — so the refiner should escalate rather than guess.

## Raw request

> Make pipeline runs resumable across a machine restart.

## Why this is high-ambiguity

At least two materially different readings are plausible, and picking wrong would invalidate
most of the resulting spec (reversal cost: high) — exactly the escalate condition (design doc
§7/§8):

1. **Already-true reading:** the state directory + history file already make an existing
   pipeline resumable (`lib/state.py`, Step 2) — this request is actually about verifying/
   documenting that guarantee, not building anything new.
2. **New-capability reading:** the request wants the *orchestrator process itself* to survive a
   host restart unattended (e.g. a systemd unit / relaunch mechanism that re-invokes Claude Code
   and resumes every in-flight pipeline automatically) — a substantially larger feature with a
   different spec entirely.
3. A narrower middle reading is also plausible: only make the *resume command* more convenient
   (e.g. a single `/pipeline:run --resume <id>` instead of re-describing the task), without any
   new automatic-relaunch machinery.

## Expected agent behavior (for manual dogfooding)

- Refiner should identify at least two of the above readings, recognize they diverge enough to
  produce different specs, and escalate a **single batched question** (not ask one question,
  wait, ask another) through the orchestrator before writing `refined_spec` — per the "batch, not
  drip" rule.
- Once answered, the refiner finishes the spec consistent with the chosen reading, journals the
  answer (`status: acknowledged`), and proceeds to G1 as normal.
