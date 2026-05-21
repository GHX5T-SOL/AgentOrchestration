import asyncio

from src.common.events import EventRetentionPipeline
from src.orchestrator.engine import OrchestrationEngine


def test_engine_records_lifecycle_events_to_operational_and_audit_stores():
    events = EventRetentionPipeline()
    engine = OrchestrationEngine(event_pipeline=events)
    agent_id = engine.registry.register("worker", "test.worker")
    task = {"id": "task-1", "target_agent": agent_id, "type": "demo"}

    asyncio.run(engine._execute_task(task))

    assert [record.event_type for record in events.operational_logs] == [
        "task.started",
        "task.completed",
    ]
    assert [record.event_type for record in events.audit_records] == [
        "task.started",
        "task.completed",
    ]
    assert all(record.digest for record in events.audit_records)


def test_engine_records_failed_task_events_to_separate_audit_store():
    events = EventRetentionPipeline()
    engine = OrchestrationEngine(event_pipeline=events)
    task = {"id": "task-1", "target_agent": "missing", "type": "demo"}

    asyncio.run(engine._execute_task(task))

    assert [record.event_type for record in events.operational_logs] == [
        "task.started",
        "task.failed",
    ]
    assert [record.event_type for record in events.audit_records] == [
        "task.started",
        "task.failed",
    ]
    assert events.audit_records[-1].payload["error_type"] == "ValueError"
