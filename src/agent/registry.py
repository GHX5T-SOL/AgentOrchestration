"""Agent Registry — Manages agent lifecycle and metadata."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

ResolutionCacheKey = Tuple[str, Optional[str], Optional[str]]


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._resolution_cache: Dict[ResolutionCacheKey, Dict[str, Any]] = {}
        self._permission_version = 0
        self._authorization_audit: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        config = dict(config or {})
        config["permissions"] = sorted(
            self._normalize_permissions(config.get("permissions", []))
        )
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._invalidate_resolution_cache(agent_type=agent_type)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def resolve(
        self,
        agent_type: str,
        required_permission: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve an agent without trusting stale authorization decisions."""
        cache_key = (agent_type, required_permission, workspace)
        cached = self._resolution_cache.get(cache_key)
        if cached:
            agent = self._agents.get(cached["agent_id"])
            if self._can_resolve(
                agent,
                agent_type,
                required_permission,
                workspace,
            ):
                cached["permission_version"] = self._permission_version
                self._record_authorization_decision(
                    "allow",
                    "cached_resolution_revalidated",
                    agent_type,
                    required_permission,
                    agent["id"],
                )
                return agent

            self._resolution_cache.pop(cache_key, None)
            self._record_authorization_decision(
                "deny",
                "cached_resolution_invalidated",
                agent_type,
                required_permission,
                cached.get("agent_id"),
            )

        for agent in self._agents.values():
            if self._can_resolve(
                agent,
                agent_type,
                required_permission,
                workspace,
            ):
                self._resolution_cache[cache_key] = {
                    "agent_id": agent["id"],
                    "permission_version": self._permission_version,
                }
                self._record_authorization_decision(
                    "allow",
                    "fresh_resolution",
                    agent_type,
                    required_permission,
                    agent["id"],
                )
                return agent

        self._record_authorization_decision(
            "deny",
            "no_authorized_agent",
            agent_type,
            required_permission,
        )
        return None

    def update_permissions(
        self,
        agent_id: str,
        permissions: List[str],
    ) -> bool:
        if agent_id not in self._agents:
            return False

        self._agents[agent_id]["config"]["permissions"] = sorted(
            self._normalize_permissions(permissions)
        )
        self._agents[agent_id]["updated_at"] = time.time()
        self._permission_version += 1
        self._invalidate_resolution_cache(agent_id=agent_id)
        self._record_authorization_decision(
            "defer",
            "permissions_changed_cache_invalidated",
            self._agents[agent_id]["type"],
            None,
            agent_id,
        )
        return True

    def authorization_decisions(self) -> List[Dict[str, Any]]:
        return [dict(decision) for decision in self._authorization_audit]

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_resolution_cache(agent_id=agent_id)
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._invalidate_resolution_cache(agent_id=agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def _can_resolve(
        self,
        agent: Optional[Dict[str, Any]],
        agent_type: str,
        required_permission: Optional[str],
        workspace: Optional[str],
    ) -> bool:
        if not agent or agent["type"] != agent_type:
            return False
        if agent["status"] in {
            AgentStatus.STOPPED.value,
            AgentStatus.FAILED.value,
            AgentStatus.TERMINATED.value,
        }:
            return False

        config = agent.get("config", {})
        if workspace is not None and config.get("workspace") != workspace:
            return False
        if required_permission is None:
            return True

        permissions = self._normalize_permissions(
            config.get("permissions", [])
        )
        return required_permission in permissions

    def _invalidate_resolution_cache(
        self,
        agent_id: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> None:
        if agent_id is None and agent_type is None:
            self._resolution_cache.clear()
            return

        stale_keys = [
            key
            for key, cached in self._resolution_cache.items()
            if cached["agent_id"] == agent_id or key[0] == agent_type
        ]
        for key in stale_keys:
            self._resolution_cache.pop(key, None)

    def _normalize_permissions(self, permissions: Any) -> Set[str]:
        if permissions is None:
            return set()
        if not isinstance(permissions, (list, tuple, set)):
            raise ValueError(
                "permissions must be a list of non-empty strings"
            )

        normalized: Set[str] = set()
        for permission in permissions:
            if not isinstance(permission, str) or not permission.strip():
                raise ValueError(
                    "permissions must be a list of non-empty strings"
                )
            normalized.add(permission.strip())
        return normalized

    def _record_authorization_decision(
        self,
        decision: str,
        reason: str,
        agent_type: str,
        required_permission: Optional[str],
        agent_id: Optional[str] = None,
    ) -> None:
        self._authorization_audit.append({
            "decision": decision,
            "reason": reason,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "required_permission": required_permission,
            "permission_version": self._permission_version,
            "timestamp": time.time(),
        })

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
