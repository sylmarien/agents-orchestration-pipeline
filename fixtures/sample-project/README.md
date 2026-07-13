# sample-project

Verification fixture for [Step 4](../../docs/implementation/step-04-implementer.md) onward
(`docs/implementation/README.md` §4 "Global verification assets"). A small, genuinely-buildable C
library standing in for the design doc's own example toolchain (§9 knob registry: `bazel
build/test`, `clang-format`, `clang-tidy`) — same shape (compile, test, format-check, lint), no
Bazel dependency, so the implementer's inner quality loop runs against real tools instead of
mocks.

- `include/intstack.h` / `src/intstack.c` — a fixed-capacity `int` stack.
- `tests/test_intstack.c` — a tiny self-contained test runner (no external framework): each check
  prints `[PASS] <name>` or `[FAIL] <name>: <message>` and the binary exits non-zero if any check
  failed. `lib/checks.py`'s test-result parser matches this exact format.
- `Makefile` targets: `build` (compiles the library alone), `test` (builds + runs the test
  binary), `format-check` (`clang-format --dry-run -Werror`), `lint` (`clang-tidy`) — auto-detected
  by `lib/checks.detect_checks`.

This fixture ships green as committed: `intstack_peek` is deliberately absent, reserved for
`fixtures/tasks/impl-add-peek.md` to ask the implementer to add test-first.
