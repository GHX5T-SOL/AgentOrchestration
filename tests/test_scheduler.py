from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_transient_retry_preserves_identity_and_retry_count(self):
        now = [100.0]
        scheduler = TaskScheduler(
            retry_base_delay=2.0,
            retry_jitter=0.5,
            clock=lambda: now[0],
            jitter=lambda low, high: high,
        )
        task_id = scheduler.enqueue(
            {"type": "test"},
            priority=7,
        )

        import asyncio
        task = asyncio.run(scheduler.dequeue())
        assert task["id"] == task_id

        assert scheduler.fail(task_id, reason="transient_queue_error")
        assert scheduler.retry_audit()[-1] == {
            "task_id": task_id,
            "decision": "retry",
            "reason": "transient_queue_error",
            "retries": 1,
            "delay": 2.5,
        }

        assert asyncio.run(scheduler.dequeue()) is None

        now[0] += 2.5
        retried = asyncio.run(scheduler.dequeue())
        assert retried["id"] == task_id
        assert retried["retries"] == 1
        assert retried["state"] == "in_flight"

    def test_duplicate_fail_does_not_schedule_multiple_retries(self):
        now = [100.0]
        scheduler = TaskScheduler(clock=lambda: now[0], jitter=lambda *_: 0.0)
        task_id = scheduler.enqueue({"type": "test"})

        import asyncio
        asyncio.run(scheduler.dequeue())

        assert scheduler.fail(task_id, reason="transient_queue_error")
        assert not scheduler.fail(task_id, reason="transient_queue_error")
        assert [
            record for record in scheduler.retry_audit()
            if record["decision"] == "retry"
        ] == [{
            "task_id": task_id,
            "decision": "retry",
            "reason": "transient_queue_error",
            "retries": 1,
            "delay": 0.25,
        }]

    def test_worker_crash_redelivery_is_throttled(self):
        now = [100.0]
        scheduler = TaskScheduler(
            max_retries=4,
            retry_base_delay=0.0,
            retry_jitter=0.0,
            poison_redelivery_threshold=2,
            poison_redelivery_delay=10.0,
            clock=lambda: now[0],
            jitter=lambda *_: 0.0,
        )
        task_id = scheduler.enqueue(
            {"type": "test"},
            queue="critical",
            priority=5,
        )

        import asyncio
        first = asyncio.run(scheduler.dequeue("critical"))
        assert first["id"] == task_id

        assert scheduler.fail(task_id, reason="worker_crash")
        assert asyncio.run(scheduler.dequeue()) is None
        second = asyncio.run(scheduler.dequeue("critical"))
        assert second["id"] == task_id
        assert second["retries"] == 1

        assert scheduler.fail(task_id, reason="worker_crash")
        audit = scheduler.retry_audit()[-1]
        assert audit == {
            "task_id": task_id,
            "decision": "redelivery_throttled",
            "reason": "worker_crash",
            "retries": 2,
            "recent_failures": 2,
            "delay": 10.0,
        }
        assert asyncio.run(scheduler.dequeue()) is None

        now[0] += 10.0
        assert asyncio.run(scheduler.dequeue()) is None
        redelivered = asyncio.run(scheduler.dequeue("critical"))
        assert redelivered["id"] == task_id
        assert redelivered["retries"] == 2
        assert redelivered["state"] == "in_flight"
        assert redelivered["redelivery_throttled_until"] == 110.0

    def test_terminal_completion_wins_over_stale_retry_failure(self):
        scheduler = TaskScheduler()
        task_id = scheduler.enqueue({"type": "test"})

        import asyncio
        asyncio.run(scheduler.dequeue())

        assert scheduler.complete(task_id)
        assert not scheduler.fail(task_id)
        assert scheduler.terminal_outcome(task_id)["state"] == "completed"

    def test_non_transient_failure_records_one_terminal_outcome(self):
        scheduler = TaskScheduler()
        task_id = scheduler.enqueue({"type": "test"})

        import asyncio
        asyncio.run(scheduler.dequeue())

        assert not scheduler.fail(
            task_id,
            transient=False,
            reason="handler_error",
        )
        assert not scheduler.complete(task_id)
        outcome = scheduler.terminal_outcome(task_id)
        assert outcome["state"] == "failed"
        assert outcome["reason"] == "handler_error"
        assert outcome["retries"] == 1

# 2019-01-09T19:07:03 update

# 2019-02-18T12:30:02 update

# 2019-04-11T16:04:51 update

# 2019-04-17T16:25:46 update

# 2019-05-24T19:32:13 update

# 2019-07-02T12:54:25 update

# 2019-07-03T20:37:00 update

# 2019-08-21T19:37:17 update

# 2019-10-18T10:30:31 update

# 2019-10-25T09:01:38 update

# 2019-10-29T12:59:34 update

# 2019-11-05T10:07:06 update

# 2019-11-11T10:43:52 update

# 2020-01-17T13:40:02 update

# 2020-02-07T14:06:34 update

# 2020-04-03T08:53:40 update

# 2020-04-06T19:36:29 update

# 2020-05-12T11:51:05 update

# 2020-08-17T08:37:15 update

# 2020-09-15T10:39:38 update

# 2020-10-06T11:26:19 update

# 2020-10-21T13:32:43 update

# 2020-12-14T18:18:36 update

# 2020-12-23T17:15:03 update

# 2021-01-25T16:29:00 update

# 2021-02-23T11:23:50 update

# 2021-03-19T12:21:19 update

# 2021-07-29T18:48:25 update

# 2021-08-25T12:46:58 update

# 2021-09-09T16:27:13 update

# 2021-12-16T12:05:30 update

# 2022-05-07T14:05:12 update

# 2022-07-18T20:52:29 update

# 2022-07-31T18:42:26 update

# 2022-09-09T13:10:08 update

# 2023-01-04T15:16:57 update

# 2023-01-17T14:49:04 update

# 2023-02-15T13:51:30 update

# 2023-03-08T09:15:53 update

# 2023-03-23T16:32:20 update

# 2023-03-28T09:32:01 update

# 2023-05-05T17:28:22 update

# 2023-06-01T08:13:52 update

# 2023-06-20T09:58:10 update

# 2023-07-04T16:14:34 update

# 2023-07-17T20:49:40 update

# 2023-12-26T11:49:18 update

# 2024-05-27T11:00:06 update

# 2024-07-04T08:53:03 update

# 2024-07-18T16:19:02 update

# 2024-08-07T09:35:35 update

# 2024-08-22T14:32:14 update

# 2025-05-20T14:19:23 update

# 2025-07-17T17:54:48 update

# 2025-07-28T13:06:30 update

# 2025-12-22T19:05:25 update

# 2026-01-08T18:43:02 update

# 2026-01-12T16:53:28 update

# 2026-04-16T16:58:23 update
