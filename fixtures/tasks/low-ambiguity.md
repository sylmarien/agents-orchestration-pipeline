# Fixture: low-ambiguity task

Step 3 Tier-2 verification input (docs/implementation/step-03-refiner-designer.md). A raw task
description with essentially one reasonable reading, so the refiner should resolve everything
itself (decide + journal, at most `low`/`medium` reversal cost) and never escalate.

## Raw request

> Add a `--version` flag to the CLI entry point that prints the plugin's version (from
> `.claude-plugin/plugin.json`) and exits 0. If the flag is combined with any other argument,
> print an error to stderr and exit 1.

## Why this is low-ambiguity

- The output source (`plugin.json`'s `version` field) is unambiguous — there is exactly one
  version string in the repo.
- The exit-code and combined-flag behavior are both stated explicitly.
- The only open question ("what if `--version` appears twice") has a single reasonable reading
  (still just print the version once) with a trivially low reversal cost — decide-and-journal
  territory, not an escalation.

## Expected agent behavior (for manual dogfooding)

- Refiner produces a `refined_spec` with mechanically-testable acceptance criteria (e.g. "running
  `<cli> --version` exits 0 and stdout equals the `version` field of `plugin.json`"; "running
  `<cli> --version --foo` exits 1 and stderr is non-empty") and pauses at G1 with **no**
  escalation.
- Designer maps every criterion to at least one test case and pauses at G2 with no `spec_gap`.
