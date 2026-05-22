"""Agent Registry — Manages agent lifecycle and metadata."""

import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from src.common.metrics import metrics

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class DuplicateCapabilityError(ValueError):
    """Raised when a plugin attempts to claim an existing capability name."""


class AgentRegistry:
    def __init__(
        self,
        storage_backend: str = "memory",
        metrics_collector=metrics,
    ):
        self.storage_backend = storage_backend
        self._metrics = metrics_collector
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._plugins: Dict[str, Dict[str, Any]] = {}
        self._capability_index: Dict[str, str] = {}
        self._resolution_cache: Dict[str, str] = {}
        self._plugin_decisions: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

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
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def register_plugin(
        self,
        name: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        replace: bool = False,
    ) -> str:
        plugin_name = self._normalize_plugin_name(name)
        normalized_capabilities = self._normalize_capabilities(capabilities)

        if plugin_name in self._plugins and not replace:
            self._reject_plugin_registration(
                plugin_name,
                normalized_capabilities,
                reason="plugin_already_registered",
                conflicts={plugin_name: normalized_capabilities},
            )

        conflicts = self._find_capability_conflicts(
            plugin_name,
            normalized_capabilities,
            replace=replace,
        )
        if conflicts:
            self._reject_plugin_registration(
                plugin_name,
                normalized_capabilities,
                reason="duplicate_capability",
                conflicts=conflicts,
            )

        previous_capabilities = set(
            self._plugins.get(plugin_name, {}).get("capabilities", [])
        )
        changed_capabilities = (
            previous_capabilities | set(normalized_capabilities)
        )

        for capability in previous_capabilities:
            self._capability_index.pop(capability, None)

        self._plugins[plugin_name] = {
            "name": plugin_name,
            "capabilities": list(normalized_capabilities),
            "metadata": dict(metadata or {}),
            "registered_at": time.time(),
        }
        for capability in normalized_capabilities:
            self._capability_index[capability] = plugin_name

        self._invalidate_resolution_cache(changed_capabilities)
        self._record_plugin_decision(
            "accepted",
            plugin_name,
            normalized_capabilities,
            reason="registered",
        )
        self._metrics.increment("registry.plugin_registration.accepted")
        logger.info(
            "plugin registration accepted",
            extra={
                "plugin": plugin_name,
                "capability_count": len(normalized_capabilities),
            },
        )
        return plugin_name

    def unregister_plugin(self, name: str) -> bool:
        plugin_name = self._normalize_plugin_name(name)
        plugin = self._plugins.pop(plugin_name, None)
        if not plugin:
            return False

        capabilities = set(plugin["capabilities"])
        for capability in capabilities:
            self._capability_index.pop(capability, None)
        self._invalidate_resolution_cache(capabilities)
        self._record_plugin_decision(
            "accepted",
            plugin_name,
            list(capabilities),
            reason="unregistered",
        )
        self._metrics.increment("registry.plugin_registration.unregistered")
        return True

    def resolve_capability(self, capability: str) -> Optional[Dict[str, Any]]:
        normalized_capability = self._normalize_capability(capability)
        cached_plugin = self._resolution_cache.get(normalized_capability)
        plugin_name = (
            cached_plugin or
            self._capability_index.get(normalized_capability)
        )
        if not plugin_name:
            self._metrics.increment("registry.capability_resolution.miss")
            return None

        self._resolution_cache[normalized_capability] = plugin_name
        self._metrics.increment("registry.capability_resolution.hit")
        return self._copy_plugin(self._plugins[plugin_name])

    def plugin_decisions(self) -> List[Dict[str, Any]]:
        return [dict(decision) for decision in self._plugin_decisions]

    def _normalize_plugin_name(self, name: str) -> str:
        plugin_name = name.strip()
        if not plugin_name:
            raise ValueError("plugin name must not be empty")
        return plugin_name

    def _normalize_capabilities(self, capabilities: List[str]) -> List[str]:
        normalized = [
            self._normalize_capability(capability)
            for capability in capabilities
        ]
        if not normalized:
            raise ValueError("plugin must declare at least one capability")

        duplicates = sorted({
            capability for capability in normalized
            if normalized.count(capability) > 1
        })
        if duplicates:
            self._reject_plugin_registration(
                "<pending>",
                normalized,
                reason="duplicate_capability",
                conflicts={"self": duplicates},
            )
        return normalized

    def _normalize_capability(self, capability: str) -> str:
        normalized = capability.strip().lower()
        if not normalized:
            raise ValueError("capability name must not be empty")
        return normalized

    def _find_capability_conflicts(
        self,
        plugin_name: str,
        capabilities: List[str],
        replace: bool,
    ) -> Dict[str, List[str]]:
        conflicts: Dict[str, List[str]] = {}
        for capability in capabilities:
            owner = self._capability_index.get(capability)
            if owner and (owner != plugin_name or not replace):
                conflicts.setdefault(owner, []).append(capability)
        return conflicts

    def _reject_plugin_registration(
        self,
        plugin_name: str,
        capabilities: List[str],
        reason: str,
        conflicts: Dict[str, List[str]],
    ) -> None:
        sanitized_conflicts = {
            owner: sorted(capability_names)
            for owner, capability_names in conflicts.items()
        }
        self._record_plugin_decision(
            "rejected",
            plugin_name,
            capabilities,
            reason=reason,
            conflicts=sanitized_conflicts,
        )
        self._metrics.increment("registry.plugin_registration.rejected")
        logger.warning(
            "plugin registration rejected",
            extra={
                "plugin": plugin_name,
                "reason": reason,
                "conflict_owners": sorted(sanitized_conflicts),
            },
        )
        raise DuplicateCapabilityError(
            f"plugin {plugin_name!r} rejected: {reason}"
        )

    def _record_plugin_decision(
        self,
        decision: str,
        plugin_name: str,
        capabilities: List[str],
        reason: str,
        conflicts: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self._plugin_decisions.append({
            "decision": decision,
            "plugin": plugin_name,
            "capabilities": sorted(capabilities),
            "reason": reason,
            "conflicts": conflicts or {},
            "timestamp": time.time(),
        })

    def _invalidate_resolution_cache(self, capabilities) -> None:
        for capability in capabilities:
            self._resolution_cache.pop(capability, None)

    def _copy_plugin(self, plugin: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": plugin["name"],
            "capabilities": list(plugin["capabilities"]),
            "metadata": dict(plugin["metadata"]),
            "registered_at": plugin["registered_at"],
        }

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
