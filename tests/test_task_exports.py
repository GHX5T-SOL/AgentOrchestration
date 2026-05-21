import csv
import io
import json

import pytest

from src.orchestrator.task_exports import (
    REDACTED,
    UnclassifiedExportFieldError,
    serialize_tasks_for_csv,
    serialize_tasks_for_json,
    serialize_tasks_for_ui,
)


def _task_record():
    return {
        "id": "task-1",
        "type": "email.sync",
        "status": "completed",
        "target_agent": "agent-1",
        "queue": "default",
        "priority": 5,
        "retries": 1,
        "enqueued_at": 123.4,
        "payload": {
            "account": "customer-1",
            "api_token": "tok_live_secret",
            "steps": [
                {
                    "name": "fetch",
                    "password": "raw-password",
                }
            ],
        },
        "result": {
            "rows": 3,
            "service_secret": "private-result",
        },
        "internal_metadata": {
            "worker_pid": 42,
            "host": "runner-1",
        },
        "debug_context": "stack frame with private internals",
    }


def test_json_and_ui_exports_share_redaction_policy():
    json_records = json.loads(serialize_tasks_for_json([_task_record()]))
    ui_records = serialize_tasks_for_ui([_task_record()])

    assert json_records == ui_records
    exported = json_records[0]
    assert "internal_metadata" not in exported
    assert "debug_context" not in exported
    assert exported["payload"]["api_token"] == REDACTED
    assert exported["payload"]["steps"][0]["password"] == REDACTED
    assert exported["result"]["service_secret"] == REDACTED


def test_csv_export_uses_same_redaction_policy():
    csv_export = serialize_tasks_for_csv([_task_record()])
    rows = list(csv.DictReader(io.StringIO(csv_export)))

    assert len(rows) == 1
    assert "internal_metadata" not in rows[0]
    assert "debug_context" not in rows[0]

    payload = json.loads(rows[0]["payload"])
    result = json.loads(rows[0]["result"])
    assert payload["api_token"] == REDACTED
    assert payload["steps"][0]["password"] == REDACTED
    assert result["service_secret"] == REDACTED


def test_unclassified_task_fields_are_rejected_before_export():
    task = {
        "id": "task-2",
        "type": "email.sync",
        "workspace_id": "workspace-1",
    }

    with pytest.raises(UnclassifiedExportFieldError) as excinfo:
        serialize_tasks_for_ui([task])

    assert "workspace_id" in str(excinfo.value)
