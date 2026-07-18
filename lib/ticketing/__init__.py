"""Ticketing integration common contract (design doc §12 "Ticketing integration"; implementation
plan Step 10). A configuration knob over the already-working pipeline (`ticketing.system`,
built-in default `none`) -- when off, nothing in this package is ever invoked and no agent
behavior changes (design doc: "purely additive").

Two systems each implement this contract's per-mode pieces (`lib.ticketing.github`,
`lib.ticketing.jira`); this module holds what's system-agnostic: spawn-time mode resolution
(including `github_issues`' graceful degradation on a non-GitHub repo, and `jira`'s fail-fast on
missing `url`/`project`), reference-parsing dispatch, link rendering, status-mapping lookup, and
the create-if-missing gate. Actual ticket I/O -- fetching an issue's content, posting a comment,
transitioning status -- is host/runtime-specific and delegated the same way PR creation is for the
submitter (design doc §16): this module never makes a network call or touches a credential; it
only makes the deterministic decisions a pipeline agent needs before it goes and does that
(host-specific) I/O itself.

    resolve_mode(ticketing_config, remote_url=None) -> dict        # spawn-time validation + degrade
    parse_reference(text, system, project=None) -> dict | None      # "#42" / "PROJ-123" / a URL -> ref
    render_link(system, ref_id, *, closes=False) -> str              # "Fixes #42" / "PROJ-123"
    status_for(stage, status_mapping) -> str                         # "start"/"pr"/"merged" -> label
    should_prompt_for_creation(create_if_missing) -> bool            # "prompt"/"never" -- no "always"
"""

from __future__ import annotations

from lib.ticketing import github, jira

SYSTEMS = {"none", "github_issues", "jira"}
STAGES = {"start", "pr", "merged"}
CREATE_IF_MISSING_VALUES = {"prompt", "never"}


class TicketingError(Exception):
    """Raised for an invalid ticketing mode/config, an unknown stage, or a malformed lookup."""


def resolve_mode(ticketing_config: dict, remote_url: str | None = None) -> dict:
    """Spawn-time mode resolution (design doc §12 "Modes"). `ticketing_config` is the resolved
    `ticketing` config block (`system`, `jira`, ...); `remote_url` is the pipeline repo's `origin`
    remote (e.g. `git remote get-url origin`), or None/empty if it has none or the call failed.

    Returns `{"mode", "degraded", "reason"}`:
    - `system: "none"` -> `{"mode": "none", "degraded": False, "reason": None}`.
    - `system: "jira"` with `jira.url`/`jira.project` both set -> `{"mode": "jira", "degraded":
      False, "reason": None}`. Either missing raises `TicketingError` -- jira is always an
      explicit choice, so a half-configured one is a config error, never a silent degrade (design
      doc §12: "missing url/project fails fast at spawn").
    - `system: "github_issues"` on a GitHub `remote_url` -> `{"mode": "github_issues", "degraded":
      False, "reason": None}`. On anything else (no remote, or a non-GitHub host) -> `{"mode":
      "none", "degraded": True, "reason": "..."}` -- **never** a raised error (design doc §12:
      "the setting is ignored: the run behaves as none... never a spawn failure")."""
    system = ticketing_config.get("system", "none")
    if system not in SYSTEMS:
        raise TicketingError(f"ticketing.system {system!r} is not one of {sorted(SYSTEMS)}")

    if system == "none":
        return {"mode": "none", "degraded": False, "reason": None}

    if system == "jira":
        jira_config = ticketing_config.get("jira") or {}
        if not jira_config.get("url") or not jira_config.get("project"):
            raise TicketingError(
                "ticketing.system: jira requires both ticketing.jira.url and ticketing.jira.project "
                "(design doc §12: jira is always an explicit choice, so a half-configured one fails fast)"
            )
        return {"mode": "jira", "degraded": False, "reason": None}

    # system == "github_issues"
    if github.is_github_remote(remote_url):
        return {"mode": "github_issues", "degraded": False, "reason": None}
    return {
        "mode": "none",
        "degraded": True,
        "reason": (
            f"ticketing.system is github_issues but the repository's origin remote ({remote_url!r}) "
            "is not a GitHub URL; degrading to none for this run"
        ),
    }


def parse_reference(text: str, system: str, project: str | None = None) -> dict | None:
    """Dispatch to the active system's own reference parser (design doc §12 intake: "#42",
    "PROJ-123", or a ticket URL). `system: "none"` always returns None -- intake never runs when
    ticketing is off. `project` is forwarded to `lib.ticketing.jira.parse_reference` only; ignored
    for `github_issues`."""
    if system == "none":
        return None
    if system == "github_issues":
        return github.parse_reference(text)
    if system == "jira":
        return jira.parse_reference(text, project=project)
    raise TicketingError(f"system {system!r} is not one of {sorted(SYSTEMS)}")


def render_link(system: str, ref_id: str, *, closes: bool = False) -> str:
    """Dispatch to the active system's own link renderer (design doc §12 "Linking")."""
    if system == "github_issues":
        return github.render_link(ref_id, closes=closes)
    if system == "jira":
        return jira.render_link(ref_id, closes=closes)
    raise TicketingError(f"system {system!r} has no link rendering (expected github_issues or jira)")


def status_for(stage: str, status_mapping: dict) -> str:
    """Look up the ticket status/workflow-state label for `stage` (`start`, `pr`, or `merged`,
    design doc §12 "Status sync") in the resolved `ticketing.status_mapping` knob. `start` doubles
    as the revert target when a PR closes unmerged (design doc §12: "reverted to the previous
    state")."""
    if stage not in STAGES:
        raise TicketingError(f"stage {stage!r} is not one of {sorted(STAGES)}")
    if stage not in status_mapping:
        raise TicketingError(f"status_mapping is missing {stage!r}: {status_mapping!r}")
    return status_mapping[stage]


def should_prompt_for_creation(create_if_missing: str) -> bool:
    """Whether the orchestrator must ask the user before creating a ticket from the refined spec
    (design doc §12 "Spec sync": "always prompts the user first... there is deliberately no
    'always'"). `prompt` (the default) -> True, always ask; `never` -> False, never even ask --
    there is no third value that creates without confirmation."""
    if create_if_missing not in CREATE_IF_MISSING_VALUES:
        raise TicketingError(f"create_if_missing {create_if_missing!r} is not one of {sorted(CREATE_IF_MISSING_VALUES)}")
    return create_if_missing == "prompt"


def _cli(argv: list[str] | None = None) -> int:
    import json
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "usage: python -m lib.ticketing "
            "<resolve-mode|parse-reference|render-link|status-for|should-prompt-for-creation> '<json-kwargs>'",
            file=sys.stderr,
        )
        return 2
    command = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 else {}
        if command == "resolve-mode":
            print(json.dumps(resolve_mode(**kwargs)))
        elif command == "parse-reference":
            print(json.dumps(parse_reference(**kwargs)))
        elif command == "render-link":
            print(json.dumps({"link": render_link(**kwargs)}))
        elif command == "status-for":
            print(json.dumps({"status": status_for(**kwargs)}))
        elif command == "should-prompt-for-creation":
            print(json.dumps({"should_prompt": should_prompt_for_creation(**kwargs)}))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except (TicketingError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0
