import pytest

from src.common.events import EventRetentionPipeline


def test_event_pipeline_stores_operational_logs_and_audit_records_separately():
    pipeline = EventRetentionPipeline(
        operational_retention_seconds=10,
        audit_retention_seconds=100,
    )

    operational = pipeline.record_event(
        "task.started",
        {"task_id": "task-1", "workspace": "acme"},
        audit=True,
        created_at=1.0,
        event_id="evt-1",
    )

    assert pipeline.operational_logs == (operational,)
    assert len(pipeline.audit_records) == 1
    assert pipeline.audit_records[0].event_id == "evt-1"
    assert pipeline.audit_records[0].digest is not None
    assert len(pipeline.audit_records[0].digest) == 64
    assert pipeline.audit_records[0] != pipeline.operational_logs[0]


def test_operational_cleanup_cannot_delete_audit_records():
    pipeline = EventRetentionPipeline(
        operational_retention_seconds=10,
        audit_retention_seconds=100,
    )
    pipeline.record_event(
        "task.completed",
        {"task_id": "task-1"},
        audit=True,
        created_at=1.0,
    )

    removed = pipeline.cleanup_operational_logs(now=20.0)

    assert removed == 1
    assert pipeline.operational_logs == ()
    assert len(pipeline.audit_records) == 1


def test_combined_cleanup_uses_separate_retention_policies():
    pipeline = EventRetentionPipeline(
        operational_retention_seconds=10,
        audit_retention_seconds=100,
    )
    pipeline.record_event(
        "task.completed",
        {"task_id": "task-1"},
        audit=True,
        created_at=1.0,
    )

    removed = pipeline.cleanup(now=20.0)

    assert removed == {"operational_logs": 1, "audit_records": 0}
    assert pipeline.operational_logs == ()
    assert len(pipeline.audit_records) == 1


def test_audit_records_are_append_only_and_digest_chained():
    pipeline = EventRetentionPipeline(
        operational_retention_seconds=10,
        audit_retention_seconds=100,
    )

    first = pipeline.append_audit_record(
        "task.updated",
        {"status": "running"},
        event_id="evt-1",
    )
    second = pipeline.append_audit_record(
        "task.updated",
        {"status": "running"},
        event_id="evt-1",
    )

    assert pipeline.audit_records == (first, second)
    assert first.event_id == second.event_id
    assert first.digest != second.digest


def test_audit_payloads_are_immutable_snapshots():
    payload = {"task_id": "task-1", "metadata": {"token": "redacted"}}
    pipeline = EventRetentionPipeline(
        operational_retention_seconds=10,
        audit_retention_seconds=100,
    )

    record = pipeline.append_audit_record("task.created", payload)
    payload["task_id"] = "mutated"

    assert record.payload["task_id"] == "task-1"
    with pytest.raises(TypeError):
        record.payload["task_id"] = "mutated"
