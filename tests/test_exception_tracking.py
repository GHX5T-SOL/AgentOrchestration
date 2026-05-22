import asyncio
import json
import logging

from src.common.exception_tracking import (
    sanitize_exception_context,
    sanitize_local_variables,
)
from src.common.logging import StructuredFormatter
from src.orchestrator.engine import OrchestrationEngine


def test_sanitizer_keeps_lookup_fields_from_nested_context_only():
    context = {
        "context": {
            "task": {
                "id": "task-123",
                "target_agent": "agent-1",
                "payload": {
                    "customer_email": "user@example.test",
                    "secret_token": "raw-secret",
                },
            },
            "request_body": {"password": "do-not-store"},
        },
        "exception": RuntimeError("failed while handling raw-secret"),
    }

    sanitized = sanitize_exception_context(context)

    assert sanitized == {
        "task_id": "task-123",
        "error_class": "RuntimeError",
    }
    rendered = repr(sanitized)
    assert "payload" not in rendered
    assert "raw-secret" not in rendered
    assert "user@example.test" not in rendered


def test_sanitizer_reduces_captured_locals_to_lookup_fields():
    task = {
        "id": "task-local",
        "target_agent": "agent-1",
        "payload": {"card": "4111111111111111"},
    }
    local_variables = {
        "task": task,
        "payload": task["payload"],
        "raw_response": {"authorization": "Bearer secret"},
    }

    sanitized = sanitize_local_variables(
        local_variables,
        ValueError("authorization failure for 4111111111111111"),
    )

    assert sanitized == {
        "task_id": "task-local",
        "error_class": "ValueError",
    }
    assert "4111111111111111" not in repr(sanitized)
    assert "Bearer secret" not in repr(sanitized)


def test_structured_formatter_sanitizes_exception_context_extra():
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        10,
        "failed",
        (),
        None,
    )
    record.exception_context = {
        "task": {"id": "task-log", "payload": {"api_key": "secret"}},
        "exception": RuntimeError("secret"),
    }

    log_entry = json.loads(formatter.format(record))

    assert log_entry["exception_context"] == {
        "task_id": "task-log",
        "error_class": "RuntimeError",
    }
    assert "secret" not in json.dumps(log_entry)


def test_engine_error_hooks_receive_sanitized_exception_event():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("agent-1", "worker.processor")
    captured = []

    async def handler(context, exc):
        captured.append((context, exc))

    async def failing_run(agent, task):
        raise RuntimeError("raw token from payload")

    engine.register_hook("on_error", handler)
    engine._run_agent_task = failing_run
    task = {
        "id": "task-hook",
        "target_agent": agent_id,
        "payload": {"token": "raw-token"},
    }

    asyncio.run(engine._execute_task(task))

    assert captured
    context, exc = captured[0]
    assert isinstance(exc, RuntimeError)
    assert context == {
        "task_id": "task-hook",
        "error_class": "RuntimeError",
    }
    assert "raw-token" not in repr(context)
