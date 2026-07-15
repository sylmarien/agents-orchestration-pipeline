"""Claude Code `PreToolUse` hook enforcing agent-pipeline's sandbox (design doc §16 "Permissions
and sandboxing"; implementation plan Step 7). Trusted-environment scope: guards against accidental
damage and runaway autonomy, not a malicious insider or adversarial input (§16).

Registered in `hooks.json` on `Bash|Write|Edit|NotebookEdit`. Reads the standard Claude Code hook
JSON payload from stdin -- notably `tool_name`, `tool_input`, `cwd` (the orchestrator's own
repo_root: pipeline agents are spawned as Task-tool subagents that never `cd`, always passing
`repo_root`/absolute paths explicitly instead, per every `agents/*.md` file's own convention) and
`agent_type` (the calling subagent's `name`, present only when the hook fires inside one -- absent
means the orchestrator itself is the caller). Writes a `hookSpecificOutput` decision to stdout and
always exits 0; Claude Code, not this script, is what actually blocks the tool call.

    evaluate(payload) -> dict        # {"permissionDecision", "permissionDecisionReason"}

Three rules (§16), each independently testable:
  - Git/publishing authority: no push to the default branch, ever; only the `submitter` agent may
    push a branch, force-push, or create a PR.
  - Filesystem confinement: Write/Edit/NotebookEdit may only target the pipeline's worktree root
    or state-directory root (both computed from `cwd`, mirroring `lib.worktree`/`lib.state`'s own
    defaults, with a project `worktree.root` override honored the same way `lib.worktree` does).
  - Network egress: a Bash command invoking a known network tool (curl, wget, pip, npm, git, ...)
    against a host outside a small fixed allow-list is never run autonomously -- it routes to the
    human (`permissionDecision: "ask"`) instead of being denied outright or silently allowed.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.resolve_config import load_yaml  # noqa: E402
from lib.state import default_state_root  # noqa: E402
from lib.worktree import resolve_root  # noqa: E402

# No agent may push to (or otherwise target) these branch names, submitter included (§16).
DEFAULT_BRANCH_NAMES = {"main", "master"}

# The only agent identity allowed to push a branch, force-push, or create a PR (§16). Matched
# against the hook payload's `agent_type` (the subagent's `name`; a plugin-scoped value like
# "agent-pipeline:submitter" is normalized to its last ":"-separated segment).
SUBMITTER_AGENT = "submitter"

# Fixed allow-list for autonomous network egress (§16: "an allow-listed set of domains"). The
# design doc's knob registry (§9) defines no config knob for this list, so it is a constant here
# rather than a project-configurable value; a fetch to anything else always routes to the human.
ALLOWED_EGRESS_DOMAINS = {
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
}

# Bash command names that plausibly reach the network -- only these trigger the egress check.
NETWORK_COMMANDS = {"curl", "wget", "pip", "pip3", "npm", "npx", "yarn", "pnpm", "go", "gem", "git"}

# Git global flags that consume a following argument, so subcommand detection can skip past them
# (agent prompts throughout this plugin favor `git -C <repo_root> ...` over `cd`).
_GIT_FLAGS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}

_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\|")
_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://([^/\s'\"]+)")
_SCP_LIKE_RE = re.compile(r"(?:^|[\s@])([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}):(?!//)")

_PR_CREATE_PATTERNS = [
    re.compile(r"^gh\s+pr\s+create\b"),
    re.compile(r"^hub\s+pull-request\b"),
    re.compile(r"^glab\s+mr\s+create\b"),
]


# --------------------------------------------------------------------------------------
# Decision helpers
# --------------------------------------------------------------------------------------


def _allow(reason: str = "") -> dict[str, str]:
    return {"permissionDecision": "allow", "permissionDecisionReason": reason}


def _deny(reason: str) -> dict[str, str]:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def _ask(reason: str) -> dict[str, str]:
    return {"permissionDecision": "ask", "permissionDecisionReason": reason}


def _agent_name(agent_type: str | None) -> str | None:
    if not agent_type:
        return None
    return agent_type.rsplit(":", 1)[-1]


# --------------------------------------------------------------------------------------
# Git / publishing authority
# --------------------------------------------------------------------------------------


def _segments(command: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_SPLIT_RE.split(command) if s.strip()]


def _tokenize(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return []


def _parse_git_invocation(tokens: list[str]) -> dict[str, Any] | None:
    if not tokens or tokens[0] != "git":
        return None
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        flag = tokens[i]
        i += 2 if flag in _GIT_FLAGS_WITH_VALUE else 1
    if i >= len(tokens):
        return None
    return {"subcommand": tokens[i], "args": tokens[i + 1 :]}


def _analyze_push(args: list[str]) -> dict[str, Any]:
    force = False
    positionals: list[str] = []
    for tok in args:
        if tok in ("--force", "-f") or tok.startswith("--force-with-lease"):
            force = True
        elif tok.startswith("-"):
            continue
        else:
            positionals.append(tok)

    branches: set[str] = set()
    for refspec in positionals[1:]:  # positionals[0], if present, is the remote
        spec = refspec[1:] if refspec.startswith("+") else refspec
        if refspec.startswith("+"):
            force = True
        target = spec.split(":")[-1] if ":" in spec else spec
        target = target.rsplit("/", 1)[-1]
        if target:
            branches.add(target)

    return {"branches": branches, "force": force}


def _is_pr_create(segment: str) -> bool:
    return any(p.match(segment) for p in _PR_CREATE_PATTERNS)


def _check_publishing_authority(segment: str, tokens: list[str], agent: str | None) -> dict | None:
    git = _parse_git_invocation(tokens)
    if git and git["subcommand"] == "push":
        analysis = _analyze_push(git["args"])
        default_hit = analysis["branches"] & DEFAULT_BRANCH_NAMES
        if default_hit:
            return _deny(
                f"push to the default branch ({', '.join(sorted(default_hit))}) is never permitted, "
                "for any agent (design doc §16)"
            )
        if agent != SUBMITTER_AGENT:
            return _deny(
                "only the submitter may push a branch or force-push; "
                f"agent {agent!r} is not permitted (design doc §16)"
            )
        return None

    if _is_pr_create(segment) and agent != SUBMITTER_AGENT:
        return _deny(f"only the submitter may create the pull request; agent {agent!r} is not permitted (design doc §16)")

    return None


# --------------------------------------------------------------------------------------
# Network egress
# --------------------------------------------------------------------------------------


def _extract_hosts(segment: str) -> set[str]:
    hosts = {m.group(1).split("@")[-1].split(":")[0].lower() for m in _URL_RE.finditer(segment)}
    hosts.update(m.group(1).lower() for m in _SCP_LIKE_RE.finditer(segment))
    return {h for h in hosts if h}


def _host_allowed(host: str) -> bool:
    return host in ALLOWED_EGRESS_DOMAINS or any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_EGRESS_DOMAINS
    )


def _check_egress(tokens: list[str], segment: str) -> dict | None:
    if not tokens:
        return None
    command_name = tokens[0].rsplit("/", 1)[-1]
    if command_name not in NETWORK_COMMANDS:
        return None
    hosts = _extract_hosts(segment)
    disallowed = sorted(h for h in hosts if not _host_allowed(h))
    if disallowed:
        return _ask(
            f"network egress to non-allow-listed host(s) {disallowed} is never run autonomously; "
            "requires human approval (design doc §16)"
        )
    return None


def _evaluate_bash(command: str, agent: str | None) -> dict:
    for segment in _segments(command):
        tokens = _tokenize(segment)
        if not tokens:
            continue
        decision = _check_publishing_authority(segment, tokens, agent)
        if decision is not None:
            return decision
        decision = _check_egress(tokens, segment)
        if decision is not None:
            return decision
    return _allow()


# --------------------------------------------------------------------------------------
# Filesystem confinement
# --------------------------------------------------------------------------------------


def _configured_worktree_root(cwd: Path) -> str:
    pipeline_yaml = cwd / ".agents" / "pipeline.yaml"
    if pipeline_yaml.exists():
        try:
            data = load_yaml(pipeline_yaml)
            root = (data.get("worktree") or {}).get("root")
            if root:
                return root
        except Exception:
            # A malformed project config is a problem for the orchestrator's own config
            # resolution to surface loudly -- this hook only needs a best-effort root and must
            # never itself crash a tool call over it.
            pass
    return "../.agents-worktrees"


def _allowed_write_roots(cwd: Path) -> list[Path]:
    return [resolve_root(cwd, _configured_worktree_root(cwd)), default_state_root(cwd)]


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _evaluate_write(tool_input: dict, cwd: Path) -> dict:
    path_str = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path_str:
        return _allow()

    path = Path(path_str)
    if not path.is_absolute():
        path = cwd / path
    path = Path(path.resolve())

    if _within(path, _allowed_write_roots(cwd)):
        return _allow()
    return _deny(
        f"write to {path} is outside this pipeline's worktree/state-dir confinement (design doc §16)"
    )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def evaluate(payload: dict) -> dict:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    agent = _agent_name(payload.get("agent_type"))
    cwd = Path(payload.get("cwd") or ".")

    if tool_name == "Bash":
        return _evaluate_bash(tool_input.get("command", "") or "", agent)
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return _evaluate_write(tool_input, cwd)
    return _allow()


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        decision = evaluate(payload)
    except ValueError as exc:
        # Malformed input from Claude Code itself would be a bug upstream, not something to
        # silently swallow -- but this hook must never be the reason a tool call hangs, so allow
        # rather than block on a payload we can't parse.
        decision = _allow(f"sandbox_guard: could not parse hook input ({exc}); allowing")

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
