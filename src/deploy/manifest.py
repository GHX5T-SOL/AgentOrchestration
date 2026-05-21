"""Dry-run rendering and validation for deployment manifests."""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

SENSITIVE_KEYWORDS = (
    "api_key",
    "credential",
    "password",
    "secret",
    "token",
)


class ManifestValidationError(ValueError):
    pass


def load_manifest(path: str) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as manifest_file:
        manifest = yaml.safe_load(manifest_file) or {}

    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest must be a mapping")
    return manifest


def validate_manifest(manifest: Dict[str, Any]) -> None:
    required_string_fields = ("name", "image")
    for field in required_string_fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ManifestValidationError(
                f"manifest field '{field}' is required"
            )

    replicas = manifest.get("replicas", 1)
    if not isinstance(replicas, int) or replicas < 1:
        raise ManifestValidationError(
            "manifest field 'replicas' must be a positive integer"
        )

    env = manifest.get("env", {})
    if not isinstance(env, dict):
        raise ManifestValidationError("manifest field 'env' must be a mapping")

    resources = manifest.get("resources", {})
    if resources and not isinstance(resources, dict):
        raise ManifestValidationError(
            "manifest field 'resources' must be a mapping"
        )


def dry_run_manifest(
    manifest: Dict[str, Any],
    previous_manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    validate_manifest(manifest)
    previous_manifest = previous_manifest or {}
    return {
        "valid": True,
        "manifest": deepcopy(manifest),
        "diff": render_manifest_diff(previous_manifest, manifest),
    }


def render_manifest_diff(
    previous_manifest: Dict[str, Any],
    next_manifest: Dict[str, Any],
) -> List[Dict[str, Any]]:
    previous_flat = _flatten(redact_manifest(previous_manifest))
    next_flat = _flatten(redact_manifest(next_manifest))
    changes: List[Dict[str, Any]] = []

    for path in sorted(set(previous_flat) | set(next_flat)):
        previous_value = previous_flat.get(path)
        next_value = next_flat.get(path)
        if previous_value == next_value:
            continue
        changes.append(
            {
                "path": path,
                "before": previous_value,
                "after": next_value,
            }
        )

    return changes


def redact_manifest(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_manifest(item)
        return redacted
    if isinstance(value, list):
        return [redact_manifest(item) for item in value]
    return value


def _flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    if isinstance(value, dict):
        flattened: Dict[str, Any] = {}
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(item, child_prefix))
        return flattened
    if isinstance(value, list):
        return {
            f"{prefix}[{index}]": item
            for index, item in enumerate(value)
        }
    return {prefix: value}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(keyword in normalized for keyword in SENSITIVE_KEYWORDS)


def format_diff(changes: Iterable[Dict[str, Any]]) -> str:
    lines = []
    for change in changes:
        lines.append(
            f"{change['path']}: {change['before']!r} -> {change['after']!r}"
        )
    return "\n".join(lines)
