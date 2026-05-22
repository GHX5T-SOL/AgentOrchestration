"""Task Scheduler — Priority-based task queuing and dispatch."""

from collections import defaultdict
import heapq
import time
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4


DEFAULT_FAIRNESS_BUDGETS = {
    "urgent": 1,
    "high": 3,
    "normal": 10,
    "background": 2,
}


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

    def pop_matching(self, predicate: Callable[[Any], bool]) -> Optional[Any]:
        skipped = []
        selected = None
        while self._queue:
            entry = heapq.heappop(self._queue)
            if predicate(entry[2]):
                selected = entry[2]
                break
            skipped.append(entry)

        for entry in skipped:
            heapq.heappush(self._queue, entry)
        return selected

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(
        self,
        fairness_budgets: Optional[Dict[str, int]] = None,
        audit_limit: int = 200,
    ):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._in_flight_by_class: Dict[str, Set[str]] = defaultdict(set)
        self._fairness_budgets = dict(DEFAULT_FAIRNESS_BUDGETS)
        if fairness_budgets:
            self._fairness_budgets.update(fairness_budgets)
        self._audit_events: List[Dict[str, Any]] = []
        self._audit_limit = audit_limit
        self._metrics: Dict[str, int] = defaultdict(int)
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
        priority_class: str = "normal",
    ) -> str:
        task_id = str(uuid4())
        self._prepare_task(task, task_id, queue, priority, priority_class)
        self._push_task(task)
        return task_id

    def _prepare_task(
        self,
        task: Dict,
        task_id: str,
        queue: str,
        priority: int,
        priority_class: str,
    ) -> None:
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["queue"] = queue
        task["priority"] = priority
        task["priority_class"] = self._normalize_priority_class(priority_class)
        task["state"] = "queued"

    def _push_task(self, task: Dict) -> None:
        queue = task["queue"]
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, task.get("priority", 0))

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
        priority_class: str = "normal",
    ) -> str:
        task_id = str(uuid4())
        self._prepare_task(task, task_id, queue, priority, priority_class)
        task["state"] = "scheduled"
        self._scheduled[task_id] = {
            "task": task,
            "ready_at": time.time() + delay,
        }
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        self._promote_due_tasks()

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop_matching(self._can_dispatch)
            if task:
                priority_class = task["priority_class"]
                task["state"] = "in_flight"
                task["dispatched_at"] = time.time()
                self._in_flight[task["id"]] = task
                self._in_flight_by_class[priority_class].add(task["id"])
                self._record_decision(task, "accepted", "within_budget")
                return task
            blocked = self._queues[queue].peek()
            if blocked:
                self._record_decision(blocked, "deferred", "budget_exhausted")
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return False
        self._release_budget(task)
        task["state"] = "completed"
        self._record_decision(task, "completed", "task_finished")
        return True

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            self._release_budget(task)
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                task["queue"] = queue
                task["state"] = "queued"
                self._push_task(task)
                self._record_decision(task, "requeued", "retry_available")
                return True
            task["state"] = "failed"
            self._record_decision(task, "failed", "retry_exhausted")
        return False

    def audit_events(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def metrics_snapshot(self) -> Dict[str, int]:
        return dict(self._metrics)

    def _promote_due_tasks(self) -> None:
        now = time.time()
        expired = [
            task_id
            for task_id, scheduled in self._scheduled.items()
            if scheduled["ready_at"] <= now
        ]
        for task_id in expired:
            task = self._scheduled.pop(task_id)["task"]
            task["state"] = "queued"
            self._push_task(task)

    def _can_dispatch(self, task: Dict) -> bool:
        priority_class = task["priority_class"]
        budget = self._fairness_budgets.get(
            priority_class,
            self._fairness_budgets["normal"],
        )
        return len(self._in_flight_by_class[priority_class]) < budget

    def _release_budget(self, task: Dict) -> None:
        priority_class = task.get("priority_class", "normal")
        self._in_flight_by_class[priority_class].discard(task["id"])

    def _normalize_priority_class(self, priority_class: str) -> str:
        normalized = str(priority_class or "normal").strip().lower()
        return normalized or "normal"

    def _record_decision(self, task: Dict, decision: str, reason: str) -> None:
        priority_class = task.get("priority_class", "normal")
        event = {
            "task_id": task.get("id"),
            "task_type": task.get("type"),
            "queue": task.get("queue"),
            "priority_class": priority_class,
            "decision": decision,
            "reason": reason,
            "timestamp": time.time(),
        }
        self._audit_events.append(event)
        if len(self._audit_events) > self._audit_limit:
            self._audit_events = self._audit_events[-self._audit_limit:]
        self._metrics[f"scheduler.{decision}.{priority_class}"] += 1

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
