"""Claude Code `PreToolUse` hook enforcing a best-effort per-session token cap (design doc §10
"Resource budgets"; implementation plan Step 9). Trusted-environment scope, same as
`sandbox_guard.py`.

Claude Code has no built-in cumulative token-budget setting (design doc §10's enforcement table),
so this hook is the workable-but-partial substitute: it reads the *current session's own*
transcript (`transcript_path` in the standard hook payload), sums the usage objects on every
assistant turn so far, and blocks further tool calls once that sum reaches the project's
configured `budget.tokens` (read the same way `sandbox_guard.py` reads `worktree.root`: from
`.agents/pipeline.yaml` if present, else unlimited). This is deliberately **per-session, not
cross-session** -- summing usage across every agent a pipeline has spawned so far is the
orchestrator's own job (`lib.budget.record_usage`/`check_budget`, called after each spawn's result
carries its usage object), which is what actually drives the warn journal entry and the GB1 gate.
This hook is only the backstop against one single runaway session blowing straight through the
whole pipeline's budget before the orchestrator ever gets a turn to notice.

    parse_transcript_usage(transcript_path) -> dict     # sum of this session's own usage so far
    evaluate(payload) -> dict                            # {"permissionDecision", "permissionDecisionReason"}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.resolve_config import load_yaml  # noqa: E402

_USAGE_FIELDS = ("input_tokens", "output_tokens")


def _allow(reason: str = "") -> dict[str, str]:
    return {"permissionDecision": "allow", "permissionDecisionReason": reason}


def _deny(reason: str) -> dict[str, str]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def parse_transcript_usage(transcript_path: str | Path) -> dict[str, int]:
    """Sum `input_tokens` + `output_tokens` across every assistant turn recorded so far in this
    session's transcript (one JSON object per line). A missing, empty, or unreadable transcript
    sums to zero rather than raising -- a hook must never be the reason a tool call hangs."""
    totals = {field: 0 for field in _USAGE_FIELDS}
    path = Path(transcript_path) if transcript_path else None
    if not path or not path.exists():
        return totals

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            usage = ((record.get("message") or {}).get("usage")) or {}
            for field in _USAGE_FIELDS:
                totals[field] += int(usage.get(field, 0) or 0)
    return totals


def _configured_budget_tokens(cwd: Path) -> int | None:
    pipeline_yaml = cwd / ".agents" / "pipeline.yaml"
    if pipeline_yaml.exists():
        try:
            data = load_yaml(pipeline_yaml)
            tokens = (data.get("budget") or {}).get("tokens")
            if tokens is not None:
                return int(tokens)
        except Exception:
            # A malformed project config is the orchestrator's own config-resolution step's
            # problem to surface loudly -- this hook only needs a best-effort cap.
            pass
    return None


def evaluate(payload: dict[str, Any]) -> dict[str, str]:
    cwd = Path(payload.get("cwd") or ".")
    budget_tokens = _configured_budget_tokens(cwd)
    if budget_tokens is None:
        return _allow()

    usage = parse_transcript_usage(payload.get("transcript_path"))
    total = usage["input_tokens"] + usage["output_tokens"]
    if total >= budget_tokens:
        return _deny(
            f"budget_meter: this session alone has used {total} tokens against the pipeline's "
            f"{budget_tokens}-token budget; stop here and let the orchestrator's GB1 gate decide "
            "whether to extend, continue unmetered, or abort (design doc §10)"
        )
    return _allow()


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        decision = evaluate(payload)
    except ValueError as exc:
        decision = _allow(f"budget_meter: could not parse hook input ({exc}); allowing")

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision["permissionDecision"],
                    "permissionDecisionReason": decision["permissionDecisionReason"],
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
