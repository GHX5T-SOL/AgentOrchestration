"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import logging
import random
import time
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(
        self,
        max_retries: int = 3,
        retry_base_delay: float = 0.25,
        retry_jitter: float = 0.1,
        poison_redelivery_threshold: int = 2,
        poison_redelivery_window: float = 30.0,
        poison_redelivery_delay: float = 60.0,
        clock: Callable[[], float] = time.time,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._terminal: Dict[str, Dict[str, Any]] = {}
        self._retry_audit: List[Dict[str, Any]] = []
        self._redelivery_history: Dict[str, List[float]] = {}
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_jitter = retry_jitter
        self._poison_redelivery_threshold = poison_redelivery_threshold
        self._poison_redelivery_window = poison_redelivery_window
        self._poison_redelivery_delay = poison_redelivery_delay
        self._clock = clock
        self._jitter = jitter

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = task.setdefault("id", str(uuid4()))
        if task_id in self._terminal:
            return task_id

        task.setdefault("retries", 0)
        task["queue"] = queue
        task["priority"] = priority
        task["enqueued_at"] = self._clock()
        task["state"] = "queued"

        self._push_task(task, queue, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = task.setdefault("id", str(uuid4()))
        if task_id in self._terminal:
            return task_id

        task.setdefault("retries", 0)
        task["queue"] = queue
        task["priority"] = priority
        task["state"] = "scheduled"
        self._scheduled[task_id] = {
            "run_at": self._clock() + max(0.0, delay),
            "task": task,
            "queue": queue,
            "priority": priority,
        }
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = self._clock()
        expired = [
            tid
            for tid, record in self._scheduled.items()
            if record["run_at"] <= now
        ]
        for tid in expired:
            record = self._scheduled.pop(tid)
            if tid in self._terminal:
                continue
            task = record["task"]
            task["state"] = "queued"
            self._push_task(
                task,
                record["queue"],
                record["priority"],
            )

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task and task["id"] not in self._terminal:
                task["state"] = "in_flight"
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if not task or task_id in self._terminal:
            return False

        task["state"] = "completed"
        self._terminal[task_id] = {
            "state": "completed",
            "task_id": task_id,
            "completed_at": self._clock(),
        }
        self._retry_audit.append({
            "task_id": task_id,
            "decision": "complete",
            "retries": task.get("retries", 0),
        })
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        transient: bool = True,
        reason: str = "worker_crash",
    ) -> bool:
        task = self._in_flight.pop(task_id, None)
        if not task or task_id in self._terminal:
            return False

        task["retries"] += 1
        retry_queue = task.get("queue", queue)
        if transient and task["retries"] < self._max_retries:
            recent_failures = self._record_redelivery_failure(task_id, reason)
            if self._should_throttle_redelivery(reason, recent_failures):
                delay = self._poison_delay(recent_failures)
                task["state"] = "redelivery_throttled"
                task["redelivery_throttled_until"] = self._clock() + delay
                self.schedule(
                    task,
                    delay,
                    retry_queue,
                    priority=task.get("priority", 0),
                )
                audit_record = {
                    "task_id": task_id,
                    "decision": "redelivery_throttled",
                    "reason": reason,
                    "retries": task["retries"],
                    "recent_failures": len(recent_failures),
                    "delay": delay,
                }
                self._retry_audit.append(audit_record)
                logger.warning(
                    "Throttled poison redelivery for task %s after %s "
                    "failures",
                    task_id,
                    len(recent_failures),
                )
                return True

            delay = self._retry_delay(task["retries"])
            task["state"] = "retry_scheduled"
            task["retry_at"] = self._clock() + delay
            self.schedule(
                task,
                delay,
                retry_queue,
                priority=task.get("priority", 0),
            )
            self._retry_audit.append({
                "task_id": task_id,
                "decision": "retry",
                "reason": reason,
                "retries": task["retries"],
                "delay": delay,
            })
            return True

        task["state"] = "failed"
        self._terminal[task_id] = {
            "state": "failed",
            "task_id": task_id,
            "failed_at": self._clock(),
            "reason": reason,
            "retries": task["retries"],
        }
        self._retry_audit.append({
            "task_id": task_id,
            "decision": "terminal_failure",
            "reason": reason,
            "retries": task["retries"],
        })
        return False

    def retry_audit(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._retry_audit]

    def terminal_outcome(self, task_id: str) -> Optional[Dict[str, Any]]:
        outcome = self._terminal.get(task_id)
        return dict(outcome) if outcome else None

    def _push_task(self, task: Dict, queue: str, priority: int) -> None:
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)

    def _retry_delay(self, retries: int) -> float:
        base_delay = self._retry_base_delay * (2 ** max(0, retries - 1))
        jitter = self._jitter(0.0, self._retry_jitter)
        return base_delay + max(0.0, jitter)

    def _record_redelivery_failure(
        self,
        task_id: str,
        reason: str,
    ) -> List[float]:
        if reason not in {"worker_crash", "crash_loop", "poison_job"}:
            return []

        now = self._clock()
        history = [
            failed_at
            for failed_at in self._redelivery_history.get(task_id, [])
            if now - failed_at <= self._poison_redelivery_window
        ]
        history.append(now)
        self._redelivery_history[task_id] = history
        return history

    def _should_throttle_redelivery(
        self,
        reason: str,
        recent_failures: List[float],
    ) -> bool:
        if reason not in {"worker_crash", "crash_loop", "poison_job"}:
            return False
        return len(recent_failures) >= self._poison_redelivery_threshold

    def _poison_delay(self, recent_failures: List[float]) -> float:
        extra_failures = max(
            0,
            len(recent_failures) - self._poison_redelivery_threshold,
        )
        return self._poison_redelivery_delay * (2 ** extra_failures)

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
