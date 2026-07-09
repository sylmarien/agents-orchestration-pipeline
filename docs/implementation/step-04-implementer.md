# Step 4 — Implementer + inner green loop

| | |
|---|---|
| **Depends on** | [Step 3](step-03-refiner-designer.md) |
| **Implements** | [§2 Implementer](../agent-pipeline-design.md#implementer), [§2 draft testing reqs](../agent-pipeline-design.md#implementer), [§9 checks/implementer knobs](../agent-pipeline-design.md#knob-registry), [§6 G3](../agent-pipeline-design.md#6-human-gating) |
| **Status** | Planned |

## Goal

Replace the implementer stub with the real agent that writes the code, works test-first, and
**iterates its inner quality loop until fully green** (build + tests + static checks) before handing
off. This is the first step to run against real project tooling, so it also brings check
auto-detection and the `fixtures/sample-project`. Nodes CR→S remain stubs.

## Scope

**In:** `agents/implementer.md`; inner-loop protocol with iteration budget + escalation;
`verification_evidence` and `implementation_notes` artifacts; check auto-detection
(`checks.build/test/static`); G3 gate content; `fixtures/sample-project`.
**Out:** review of the diff (Step 5); docs (Step 6); the squash/PR (Step 7).

## Deliverables (tree delta)

```
agents/implementer.md
lib/checks.py                 # detect + run build/test/static commands; parse pass/fail
fixtures/sample-project/**    # small repo: source + tests + build/lint config
fixtures/tasks/impl-*         # tasks with known-good designs to implement
tests/test_checks.py
```

## Technical design

### Check auto-detection (`lib/checks.py`)
[§9 defaults](../agent-pipeline-design.md#knob-registry): `checks.build/test/static` are
auto-detected from the repo when not set in `pipeline.yaml` (the design's example repo resolves to
`bazel build/test`, `clang-format`, `clang-tidy`). `checks.py` detects the toolchain, exposes the
resolved commands, runs them in the worktree, and parses structured pass/fail + failing-item
detail. Project config overrides detection; the resolved commands are recorded in the manifest.
The `fixtures/sample-project` ships a small but genuine build/test/lint setup so the loop runs
against real tools rather than mocks.

### Implementer agent (`implementer.md`)
[§2 Implementer](../agent-pipeline-design.md#implementer), autonomy `lean_decide`:
- Implement **exactly** the design; journal any forced deviation; if a deviation invalidates the
  design, emit `design_infeasible` (→L5/GE1 back to designer).
- **TDD-first** (`implementer.tdd: required_when_possible`): write the design's test cases as
  *failing* tests before the production code that makes them pass — completing the traceability chain
  (criterion → test case → implemented test). When TDD is impractical, journal why and add tests
  immediately after.
- Commit in reviewable increments with descriptive messages — **working history only** (the submitter
  squashes later), so messages serve the reviewer, not the final log.
- Record `implementation_notes` (surprises, debt, follow-ups) and `verification_evidence` (build
  logs, test results, check results, and the **criterion→test map**) to the state directory.

### Inner green loop
[§2 inner loop](../agent-pipeline-design.md#implementer): `write failing tests → write code → build →
run tests → run static checks → fix → repeat`, exit only when **all green**. Budget
`implementer.inner_loop.max_iterations` (default 10); exhaustion **escalates to the orchestrator**
rather than handing off red work. Each iteration's within-stage progress is written to the node's
per-node state file so a crash resumes mid-loop.

### G3 gate
On T3 (implementer→code_reviewer), gate G3 (`implementation_done`) presents the `diff` and
`verification_evidence`. Active under `paranoid` / when added; off under `checkpoint`/`full_auto`.

## Verification

**Tier 1 — unit tests:**
- `checks.py`: detection picks the right commands for the sample project; running a green tree
  reports all-pass; a seeded failing test / lint violation is parsed as the specific failing item.

**Tier 2 — end-to-end (real R+D+I, stubbed CR→S):**
- On `fixtures/tasks/impl-*` with a valid design: implementer produces a diff in the worktree that
  **builds, passes all tests (new + pre-existing), and passes static checks**; `verification_evidence`
  maps every automatable acceptance criterion to a passing test.
- **TDD ordering:** the working history shows failing tests committed before the production code that
  greens them (or a journaled reason when TDD was impractical).
- **Loop convergence:** a task needing several iterations converges within budget; artificially
  capping `max_iterations` low forces the exhaustion escalation to the orchestrator (no red hand-off).
- **Design infeasibility:** a design with an impossible instruction triggers `design_infeasible` →
  L5; GE1 fires (design was G2-approved); rollback re-enters the designer.
- **Crash mid-loop:** killing the implementer mid-iteration and re-spawning resumes from per-node
  state.

## Definition of done

- [ ] Implementer exits only fully green (build + full test suite + static checks) in the worktree.
- [ ] Every automatable criterion covered by an implemented, passing test; evidence attached with the map.
- [ ] TDD-first honored or the exception journaled.
- [ ] Inner-loop budget enforced; exhaustion escalates, never hands off red.
- [ ] `design_infeasible` routes L5 with GE1; check commands recorded in the manifest.
