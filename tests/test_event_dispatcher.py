from src.common.metrics import MetricsCollector
from src.orchestrator.engine import EventDispatcher, OrchestrationEngine


def test_dispatcher_quarantines_unknown_event_without_state_change():
    dispatcher = EventDispatcher()
    dispatcher.dispatch(
        {
            "type": "run.started",
            "run_id": "run-private-1",
            "attempt": 1,
            "revision": 7,
            "event_id": "evt-start",
            "tenant_id": "tenant-secret",
        }
    )

    decision = dispatcher.dispatch(
        {
            "type": "run.promoted",
            "run_id": "run-private-1",
            "attempt": 1,
            "revision": 8,
            "event_id": "evt-unknown",
            "payload": {"secret": "do-not-record"},
            "tenant_id": "tenant-secret",
        }
    )

    assert not decision.accepted
    assert decision.reason == "unknown_event_type"
    assert dispatcher.get_state("run", "run-private-1") == {
        "lifecycle": "running",
        "attempt": 1,
        "revision": 7,
    }

    quarantine = dispatcher.quarantined_records()[-1]
    assert quarantine == {
        "accepted": False,
        "event_type": "run.promoted",
        "resource_kind": "unknown",
        "reason": "unknown_event_type",
    }
    assert "tenant-secret" not in str(dispatcher.audit_records())
    assert "do-not-record" not in str(dispatcher.audit_records())


def test_dispatcher_rejects_stale_attempt_during_upgrade():
    dispatcher = EventDispatcher()
    dispatcher.dispatch(
        {
            "type": "run.started",
            "run_id": "upgrade-run",
            "attempt": 1,
            "revision": 10,
            "event_id": "run-start-1",
        }
    )
    dispatcher.dispatch(
        {
            "type": "run.failed",
            "run_id": "upgrade-run",
            "attempt": 1,
            "revision": 11,
            "event_id": "run-fail-1",
        }
    )
    dispatcher.dispatch(
        {
            "type": "run.started",
            "run_id": "upgrade-run",
            "attempt": 2,
            "revision": 12,
            "event_id": "run-start-2",
        }
    )

    decision = dispatcher.dispatch(
        {
            "type": "run.completed",
            "run_id": "upgrade-run",
            "attempt": 1,
            "revision": 13,
            "event_id": "stale-complete",
        }
    )

    assert not decision.accepted
    assert decision.reason == "stale_attempt"
    assert dispatcher.get_state("run", "upgrade-run") == {
        "lifecycle": "running",
        "attempt": 2,
        "revision": 12,
    }
    quarantine = dispatcher.quarantined_records()[-1]
    assert quarantine["entity_ref"].startswith("run:")
    assert "upgrade-run" not in str(quarantine)


def test_dispatcher_rejects_duplicates_and_invalid_lifecycle():
    dispatcher = EventDispatcher()

    invalid = dispatcher.dispatch(
        {
            "type": "task.completed",
            "task_id": "task-1",
            "attempt": 1,
            "revision": 1,
            "event_id": "complete-before-start",
        }
    )
    assert not invalid.accepted
    assert invalid.reason == "invalid_lifecycle_transition"
    assert dispatcher.get_state("task", "task-1") is None

    accepted = dispatcher.dispatch(
        {
            "type": "task.queued",
            "task_id": "task-1",
            "attempt": 1,
            "revision": 2,
            "event_id": "queue-task",
        }
    )
    duplicate = dispatcher.dispatch(
        {
            "type": "task.queued",
            "task_id": "task-1",
            "attempt": 1,
            "revision": 2,
            "event_id": "queue-task",
        }
    )

    assert accepted.accepted
    assert not duplicate.accepted
    assert duplicate.reason == "duplicate_event"
    assert dispatcher.get_state("task", "task-1") == {
        "lifecycle": "queued",
        "attempt": 1,
        "revision": 2,
    }


def test_engine_exposes_event_dispatcher_boundary():
    engine = OrchestrationEngine()

    decision = engine.dispatch_event(
        {
            "type": "handler.registered",
            "handler_id": "handler-1",
            "attempt": 1,
            "revision": 1,
            "event_id": "handler-register",
        }
    )

    assert decision.accepted
    assert engine.event_dispatcher.get_state("handler", "handler-1") == {
        "lifecycle": "registered",
        "attempt": 1,
        "revision": 1,
    }


def test_dispatcher_records_sanitized_metrics():
    metrics = MetricsCollector()
    dispatcher = EventDispatcher(metrics_collector=metrics)

    dispatcher.dispatch(
        {
            "type": "handler.registered",
            "handler_id": "handler-private",
            "attempt": 1,
            "revision": 1,
            "event_id": "register-handler",
        }
    )
    dispatcher.dispatch(
        {
            "type": "handler.removed",
            "handler_id": "handler-private",
            "attempt": 1,
            "revision": 0,
            "event_id": "stale-handler-remove",
            "runtime_payload": "private-data",
        }
    )

    snapshot = metrics.snapshot()
    assert snapshot["counters"]["orchestrator.events.accepted"] == 1
    assert snapshot["counters"]["orchestrator.events.quarantined"] == 1
    stale_revision = "orchestrator.events.reason.stale_revision"
    assert snapshot["counters"][stale_revision] == 1
    assert "handler-private" not in str(dispatcher.audit_records())
    assert "private-data" not in str(dispatcher.audit_records())
