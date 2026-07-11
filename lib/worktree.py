"""Git worktree lifecycle for agent-pipeline (design doc §4 "Worktree placement and isolation").

Each pipeline (and, in a future parallel topology, each concurrently-active agent within a
pipeline) gets its own git worktree so builds that write outside the source tree (e.g. a
`../build` output directory) never collide across parallel working copies. This module resolves
the worktree's path from the `worktree.root` / `worktree.name_template` config knobs and wraps
`git worktree add` / `git worktree remove`.

    resolve_path(repo_root, worktree_root, name_template, pipeline_id, agent_id=None) -> Path
    add(repo_root, path, branch, base_ref="HEAD") -> Path
    remove(repo_root, path, force=False) -> None
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Matches the optional `[...]` segment in a name_template, e.g. `[-{agent_id}]`. When agent_id is
# falsy the whole bracketed segment (including the brackets) is dropped; otherwise the brackets
# are stripped and the segment's own placeholders (e.g. `{agent_id}`) are kept for `str.format`.
_OPTIONAL_SEGMENT_RE = re.compile(r"\[([^\]]*)\]")


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""


def _expand_optional_segments(template: str, agent_id: str | None) -> str:
    return _OPTIONAL_SEGMENT_RE.sub(lambda m: m.group(1) if agent_id else "", template)


def resolve_root(repo_root: str | Path, worktree_root: str | Path) -> Path:
    """Resolve `worktree.root`: absolute values are used as-is, relative values resolve from
    the source repo root (design doc: "a repo at /home/user/proj gets worktrees under
    /home/user/.agents-worktrees/...", i.e. the default `../.agents-worktrees` is relative to
    the repo root, not its parent)."""
    repo_root = Path(repo_root)
    if not repo_root.is_absolute():
        repo_root = repo_root.resolve()
    root = Path(worktree_root)
    if root.is_absolute():
        return root.resolve()
    return (repo_root / root).resolve()


def resolve_path(
    repo_root: str | Path,
    worktree_root: str | Path,
    name_template: str,
    pipeline_id: str,
    agent_id: str | None = None,
    repo_name: str | None = None,
) -> Path:
    """Resolve the full worktree path for a pipeline (and optionally a concurrently-active
    agent within it). `repo_name` defaults to the repo root's own directory name, preserved as
    the leaf so out-of-tree relative build paths never collide across worktrees."""
    repo_root = Path(repo_root).resolve()
    repo_name = repo_name or repo_root.name

    sub_path = _expand_optional_segments(name_template, agent_id)
    sub_path = sub_path.format(pipeline_id=pipeline_id, agent_id=agent_id or "", repo_name=repo_name)

    root = resolve_root(repo_root, worktree_root)
    return (root / sub_path).resolve()


def add(repo_root: str | Path, path: str | Path, branch: str, base_ref: str = "HEAD") -> Path:
    """`git worktree add -b <branch> <path> <base_ref>`, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(path), base_ref],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {result.stderr.strip()}")
    return path


def remove(repo_root: str | Path, path: str | Path, force: bool = False) -> None:
    """`git worktree remove <path>` -- the auto-clean step on pipeline completion (design doc:
    terminal at G8, or user stop). Does not touch the pipeline's state directory."""
    cmd = ["git", "worktree", "remove", str(path)]
    if force:
        cmd.append("--force")
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    if result.returncode != 0:
        raise WorktreeError(f"git worktree remove failed: {result.stderr.strip()}")


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python -m lib.worktree <resolve-path|add|remove> '<json-kwargs>'", file=sys.stderr)
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "resolve-path":
            print(json.dumps({"path": str(resolve_path(**kwargs))}))
        elif command == "add":
            print(json.dumps({"path": str(add(**kwargs))}))
        elif command == "remove":
            remove(**kwargs)
            print(json.dumps({"removed": True}))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (WorktreeError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
