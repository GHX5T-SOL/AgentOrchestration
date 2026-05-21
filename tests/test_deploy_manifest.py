import pytest

from src.deploy.manifest import (
    ManifestValidationError,
    dry_run_manifest,
    render_manifest_diff,
)


def test_dry_run_manifest_validates_release_candidate_and_returns_diff():
    previous = {
        "name": "agent",
        "image": "repo/agent:1",
        "replicas": 1,
        "env": {"MODE": "prod"},
    }
    candidate = {
        "name": "agent",
        "image": "repo/agent:2",
        "replicas": 2,
        "env": {"MODE": "prod"},
    }

    preview = dry_run_manifest(candidate, previous)

    assert preview["valid"] is True
    assert preview["manifest"] == candidate
    assert {
        "path": "image",
        "before": "repo/agent:1",
        "after": "repo/agent:2",
    } in preview["diff"]
    assert {"path": "replicas", "before": 1, "after": 2} in preview["diff"]


def test_invalid_manifest_fails_before_deployment_approval():
    with pytest.raises(ManifestValidationError):
        dry_run_manifest({"name": "agent", "image": "", "env": {}})


def test_review_diff_redacts_sensitive_values():
    previous = {
        "name": "agent",
        "image": "repo/agent:1",
        "env": {"API_TOKEN": "old-secret"},
    }
    candidate = {
        "name": "agent",
        "image": "repo/agent:1",
        "env": {"API_TOKEN": "new-secret", "MODE": "prod"},
    }

    diff = render_manifest_diff(previous, candidate)

    assert "old-secret" not in repr(diff)
    assert "new-secret" not in repr(diff)
    assert {
        "path": "env.API_TOKEN",
        "before": "[REDACTED]",
        "after": "[REDACTED]",
    } not in diff
    assert {"path": "env.MODE", "before": None, "after": "prod"} in diff
