"""Jira ticketing mode (design doc §12 "jira"; Q7; implementation plan Step 10). Auth is delegated
entirely to an existing Jira MCP connector or skill in the user's environment -- this module never
handles a credential and never makes a network call itself; connectivity validation at spawn
(design doc §12) is the delegated connector's job, not this module's. What this module owns is the
same deterministic slice as `lib.ticketing.github`: recognizing/parsing a Jira issue reference and
rendering the PR-body/commit-message link.

    parse_reference(text, project=None) -> dict | None   # "PROJ-123" or a /browse/ URL -> ref
    render_link(ref_id, *, closes=False) -> str
"""

from __future__ import annotations

import re

_KEY_RE = re.compile(r"\b(?P<key>[A-Z][A-Z0-9]+-\d+)\b")
_BROWSE_URL_RE = re.compile(r"/browse/(?P<key>[A-Z][A-Z0-9]+-\d+)\b")


def parse_reference(text: str, project: str | None = None) -> dict | None:
    """First Jira issue key found in free text, either bare (`PROJ-123`) or in a `/browse/` URL
    (design doc §12 intake: "PROJ-123", "or be given as a ticket URL"). When `project` is given
    (the configured `ticketing.jira.project`), a key belonging to a *different* project is
    ignored -- design doc §12 scopes intake to "issues in the configured Jira project," not any
    Jira key a task happens to mention. Returns None when the text names no matching key."""
    url_match = _BROWSE_URL_RE.search(text)
    key = url_match.group("key") if url_match else None
    if key is None:
        key_match = _KEY_RE.search(text)
        key = key_match.group("key") if key_match else None
    if key is None:
        return None
    key_project = key.rsplit("-", 1)[0]
    if project and key_project != project:
        return None
    return {"system": "jira", "id": key, "project": key_project}


def render_link(ref_id: str, *, closes: bool = False) -> str:
    """Jira has no PR-body closing keyword the way GitHub has `Fixes #N`; the key alone in the PR
    title/body is what its smart-commit integration scans for (design doc §12 "Linking"). `closes`
    is accepted for interface symmetry with `lib.ticketing.github.render_link` but never changes
    the rendered text -- the actual workflow transition happens through `status_for` and the
    delegated connector, not a magic string in the commit/PR text."""
    return ref_id
