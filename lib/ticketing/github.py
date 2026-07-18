"""GitHub-issues ticketing mode (design doc §12 "github_issues"; implementation plan Step 10).
Tickets are the repo's own GitHub issues -- no separate credential or config beyond
`ticketing.system: github_issues` itself, since it reuses whatever GitHub access the pipeline's
runtime already has (the same GitHub tooling the orchestrator/submitter/pr_shepherd use for PR
creation and PR-activity subscription). This module holds only the deterministic, host-independent
pieces: recognizing a GitHub-hosted repo from its remote URL, parsing an issue reference out of
free text, and rendering the PR-body/commit-message link -- never a network call itself; fetching
an issue's content, posting a comment, or applying a label is host/runtime-specific and delegated
the same way PR creation is for the submitter (design doc §16).

    is_github_remote(remote_url) -> bool
    parse_reference(text) -> dict | None      # "#42" or an issues URL -> {"system", "id", ...}
    render_link(ref_id, *, closes=False) -> str
"""

from __future__ import annotations

import re

_ISSUE_URL_RE = re.compile(r"github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/issues/(?P<id>\d+)\b")
_ISSUE_HASH_RE = re.compile(r"#(?P<id>\d+)\b")


def is_github_remote(remote_url: str | None) -> bool:
    """True when `remote_url` (typically `origin`'s, via `git remote get-url origin`) points at
    github.com, in either https or ssh form. `None`/empty (no remote configured, or the `git`
    call itself failed) is not a GitHub remote -- the caller's degrade path (design doc §12
    "graceful degradation") treats that the same as a non-GitHub host."""
    return bool(remote_url) and "github.com" in remote_url


def parse_reference(text: str) -> dict | None:
    """First GitHub issue reference found in free text: an issues URL, else a bare `#<n>`
    (design doc §12 intake: "a task may reference a ticket (#42 ...) or be given as a ticket
    URL"). Returns None when the text names no GitHub issue at all -- a task is not required to
    reference one even with `github_issues` active."""
    url_match = _ISSUE_URL_RE.search(text)
    if url_match:
        return {
            "system": "github_issues",
            "id": url_match.group("id"),
            "owner": url_match.group("owner"),
            "repo": url_match.group("repo"),
        }
    hash_match = _ISSUE_HASH_RE.search(text)
    if hash_match:
        return {"system": "github_issues", "id": hash_match.group("id")}
    return None


def render_link(ref_id: str, *, closes: bool = False) -> str:
    """`Fixes #42` (auto-closes the issue on merge -- the squashed commit message and the PR
    body both carry this form, design doc §12 "Linking") or `Refs #42` (mention only, no
    auto-close -- used anywhere a non-closing reference is wanted, e.g. the branch name)."""
    keyword = "Fixes" if closes else "Refs"
    return f"{keyword} #{ref_id}"
