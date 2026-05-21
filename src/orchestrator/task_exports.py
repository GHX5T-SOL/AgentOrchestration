"""Shared task export serialization policy."""

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Mapping


REDACTED = "[REDACTED]"

EXPORT_FIELDS = (
    "id",
    "type",
    "status",
    "target_agent",
    "queue",
    "priority",
    "retries",
    "enqueued_at",
    "payload",
    "result",
    "error",
)

PUBLIC_TASK_FIELDS = frozenset(EXPORT_FIELDS)
OMITTED_TASK_FIELDS = frozenset(
    {
        "debug_context",
        "handler",
        "internal_metadata",
        "internal_trace",
        "sandbox_path",
        "stack",
        "worker_pid",
    }
)
CLASSIFIED_TASK_FIELDS = PUBLIC_TASK_FIELDS | OMITTED_TASK_FIELDS

SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class UnclassifiedExportFieldError(ValueError):
    """Raised when a task field has no export policy classification."""


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, nested in value.items():
            output_key = str(key)
            if _is_sensitive_key(output_key):
                redacted[output_key] = REDACTED
            else:
                redacted[output_key] = _redact_sensitive_values(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive_values(item) for item in value]
    return value


def _validate_classified_fields(task: Mapping[str, Any]) -> None:
    unknown_fields = sorted(
        str(field)
        for field in task
        if str(field) not in CLASSIFIED_TASK_FIELDS
    )
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise UnclassifiedExportFieldError(
            "Task export fields must be classified before serialization: "
            f"{joined}"
        )


def serialize_task_for_export(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Return one task using the shared JSON, CSV, and UI export policy."""

    _validate_classified_fields(task)
    serialized: Dict[str, Any] = {}
    for field in EXPORT_FIELDS:
        if field in task:
            serialized[field] = _redact_sensitive_values(task[field])
    return serialized


def serialize_tasks_for_ui(
    tasks: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    return [serialize_task_for_export(task) for task in tasks]


def serialize_tasks_for_json(tasks: Iterable[Mapping[str, Any]]) -> str:
    return json.dumps(serialize_tasks_for_ui(tasks), sort_keys=True)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def serialize_tasks_for_csv(tasks: Iterable[Mapping[str, Any]]) -> str:
    rows = serialize_tasks_for_ui(tasks)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=EXPORT_FIELDS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {field: _csv_value(row.get(field)) for field in EXPORT_FIELDS}
        )
    return output.getvalue()
