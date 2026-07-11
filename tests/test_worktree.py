import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.worktree import WorktreeError, add, remove, resolve_path, resolve_root

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def repo(tmp_path) -> Path:
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    _run(["git", "init"], repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], repo_dir)
    _run(["git", "config", "user.name", "Test"], repo_dir)
    (repo_dir / "README.md").write_text("hello\n")
    _run(["git", "add", "README.md"], repo_dir)
    _run(["git", "commit", "-m", "initial"], repo_dir)
    return repo_dir


# --- Name-template resolution --------------------------------------------------------------


def test_single_agent_collapses_agent_id_segment(repo):
    path = resolve_path(repo, "../.agents-worktrees", "{pipeline_id}[-{agent_id}]/{repo_name}", "task1")
    assert path.name == "myrepo"
    assert path.parent.name == "task1"


def test_multi_agent_keeps_agent_id_segment(repo):
    path = resolve_path(
        repo, "../.agents-worktrees", "{pipeline_id}[-{agent_id}]/{repo_name}", "task1", agent_id="docs"
    )
    assert path.parent.name == "task1-docs"
    assert path.name == "myrepo"


def test_repo_name_leaf_preserved_and_overridable(repo):
    path = resolve_path(repo, "../.agents-worktrees", "{pipeline_id}/{repo_name}", "task1")
    assert path.name == "myrepo"

    path2 = resolve_path(repo, "../.agents-worktrees", "{pipeline_id}/{repo_name}", "task1", repo_name="custom")
    assert path2.name == "custom"


def test_relative_root_resolves_from_repo_root(repo):
    root = resolve_root(repo, "../.agents-worktrees")
    assert root == (repo.parent / ".agents-worktrees").resolve()


def test_absolute_root_used_as_is(repo, tmp_path):
    absolute = tmp_path / "somewhere-else"
    root = resolve_root(repo, str(absolute))
    assert root == absolute.resolve()


def test_relative_root_path_is_sibling_of_repo(repo):
    path = resolve_path(repo, "../.agents-worktrees", "{pipeline_id}/{repo_name}", "task1")
    assert path == (repo.parent / ".agents-worktrees" / "task1" / "myrepo").resolve()


# --- git worktree add / remove --------------------------------------------------------------


def test_add_creates_branch_and_worktree(repo, tmp_path):
    wt_path = tmp_path / "wt1"
    result = add(repo, wt_path, branch="pipeline/task1")
    assert result == wt_path
    assert (wt_path / "README.md").exists()

    branches = _run(["git", "branch", "--list", "pipeline/task1"], repo).stdout
    assert "pipeline/task1" in branches

    worktree_list = _run(["git", "worktree", "list"], repo).stdout
    assert str(wt_path) in worktree_list


def test_remove_removes_worktree(repo, tmp_path):
    wt_path = tmp_path / "wt2"
    add(repo, wt_path, branch="pipeline/task2")
    assert wt_path.exists()

    remove(repo, wt_path)

    assert not wt_path.exists()
    worktree_list = _run(["git", "worktree", "list"], repo).stdout
    assert str(wt_path) not in worktree_list


def test_remove_nonexistent_worktree_raises(repo, tmp_path):
    with pytest.raises(WorktreeError):
        remove(repo, tmp_path / "does-not-exist")


def test_add_duplicate_branch_raises(repo, tmp_path):
    add(repo, tmp_path / "wt3", branch="pipeline/task3")
    with pytest.raises(WorktreeError):
        add(repo, tmp_path / "wt3-again", branch="pipeline/task3")


# --- CLI -------------------------------------------------------------------------------------


def test_cli_malformed_json_reports_structured_error_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "lib.worktree", "resolve-path", "not-valid-json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert "error" in json.loads(result.stdout)
