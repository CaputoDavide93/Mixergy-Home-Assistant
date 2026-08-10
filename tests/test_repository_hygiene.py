"""Public repository policy checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_workflows_pin_actions_and_use_read_only_permissions() -> None:
    """CI dependencies must be immutable and tokens least-privileged."""
    action_ref = re.compile(r"^[^@]+@[0-9a-f]{40}$")

    for path in WORKFLOWS.glob("*.yaml"):
        workflow = yaml.safe_load(path.read_text())
        assert workflow.get("permissions") == {"contents": "read"}, path
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if uses := step.get("uses"):
                    assert action_ref.fullmatch(uses), f"{path}: {uses}"


def test_local_artifacts_are_ignored() -> None:
    """Machine-specific environments must never enter the public repository."""
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".test_venv/" in ignored
    assert ".pytest_cache/" in ignored
    assert ".coverage" in ignored
    assert "htmlcov/" in ignored