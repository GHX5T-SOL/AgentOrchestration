import asyncio

import pytest

from src.agent.executor import AgentExecutor


class TestAgentExecutor:
    def test_successful_execution_returns_result(self):
        async def run():
            executor = AgentExecutor()

            async def handler(agent_id, task):
                return {"ok": True, "agent": agent_id, "task": task["id"]}

            execution_id = await executor.execute(
                "agent-1",
                {"id": "task-1"},
                handler,
            )

            result = executor.get_result(execution_id)
            assert result["execution_id"] == execution_id
            assert result["agent_id"] == "agent-1"
            assert result["task_id"] == "task-1"
            assert result["result"] == {
                "ok": True,
                "agent": "agent-1",
                "task": "task-1",
            }

        asyncio.run(run())

    def test_cancel_active_execution_stores_cancelled_result(self):
        async def run():
            executor = AgentExecutor()
            started = asyncio.Event()
            release = asyncio.Event()

            async def handler(agent_id, task):
                started.set()
                await release.wait()

            execute_task = asyncio.create_task(
                executor.execute("agent-1", {"id": "task-1"}, handler)
            )

            await started.wait()
            execution_id = executor.execution_id_for(execute_task)
            assert execution_id is not None

            assert executor.cancel(execution_id)
            completed_id = await execute_task
            assert completed_id == execution_id

            result = executor.get_result(execution_id)
            assert result["execution_id"] == execution_id
            assert result["agent_id"] == "agent-1"
            assert result["task_id"] == "task-1"
            assert result["status"] == "cancelled"
            assert result["cancelled"] is True
            assert executor.cancel(execution_id) is False

        asyncio.run(run())

    def test_external_task_cancellation_still_records_result(self):
        async def run():
            executor = AgentExecutor()
            started = asyncio.Event()
            release = asyncio.Event()

            async def handler(agent_id, task):
                started.set()
                await release.wait()

            execute_task = asyncio.create_task(
                executor.execute("agent-2", {"id": "task-2"}, handler)
            )

            await started.wait()
            execution_id = executor.execution_id_for(execute_task)
            assert execution_id is not None

            execute_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execute_task

            result = executor.get_result(execution_id)
            assert result["execution_id"] == execution_id
            assert result["agent_id"] == "agent-2"
            assert result["task_id"] == "task-2"
            assert result["status"] == "cancelled"
            assert result["cancelled"] is True

        asyncio.run(run())

    def test_handler_exception_stores_error_result(self):
        async def run():
            executor = AgentExecutor()

            async def handler(agent_id, task):
                raise RuntimeError("boom")

            execution_id = await executor.execute(
                "agent-1",
                {"id": "task-1"},
                handler,
            )

            assert executor.get_result(execution_id) == {"error": "boom"}

        asyncio.run(run())
