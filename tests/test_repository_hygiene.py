"""Public repository policy checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Job-level permissions may only narrow, never widen. Everything a job in
# this repository legitimately needs is read-only.
_READ_ONLY = {"read", "none"}


def test_workflows_pin_actions_and_use_read_only_permissions() -> None:
    """CI dependencies must be immutable and tokens least-privileged."""
    action_ref = re.compile(r"^[^@]+@[0-9a-f]{40}$")

    # GitHub Actions executes both extensions; globbing only one would let a
    # future .yml workflow bypass every check here — and an empty match list
    # would pass vacuously.
    paths = sorted(WORKFLOWS.glob("*.yaml")) + sorted(WORKFLOWS.glob("*.yml"))
    assert paths, "no workflows found — glob is broken or directory moved"

    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        assert workflow.get("permissions") == {"contents": "read"}, path
        for job_name, job in workflow["jobs"].items():
            # Job-level permissions override the workflow default — the
            # standard way scopes get widened. Require any override to be
            # read-only too.
            for scope, level in (job.get("permissions") or {}).items():
                assert level in _READ_ONLY, (
                    f"{path}: job '{job_name}' widens '{scope}' to '{level}'"
                )
            for step in job.get("steps", []):
                if uses := step.get("uses"):
                    # Local composite actions ("./.github/actions/x") are
                    # pinned by the repo commit itself and cannot carry @sha.
                    if uses.startswith("./"):
                        continue
                    assert action_ref.fullmatch(uses), f"{path}: {uses}"


def test_local_artifacts_are_ignored() -> None:
    """Machine-specific environments must never enter the public repository."""
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".test_venv/" in ignored
    assert ".pytest_cache/" in ignored
    assert ".coverage" in ignored
    assert "htmlcov/" in ignored
