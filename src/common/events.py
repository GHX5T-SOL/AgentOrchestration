"""Event retention storage for operational logs and audit records."""

import json
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: float
    digest: Optional[str] = None


class EventRetentionPipeline:
    def __init__(
        self,
        operational_retention_seconds: float = 7 * 24 * 60 * 60,
        audit_retention_seconds: float = 365 * 24 * 60 * 60,
        clock: Callable[[], float] = time.time,
    ):
        if operational_retention_seconds <= 0:
            raise ValueError("operational retention must be positive")
        if audit_retention_seconds <= operational_retention_seconds:
            raise ValueError(
                "audit retention must be longer than operational retention"
            )

        self.operational_retention_seconds = operational_retention_seconds
        self.audit_retention_seconds = audit_retention_seconds
        self._clock = clock
        self._operational_logs: List[EventRecord] = []
        self._audit_records: List[EventRecord] = []

    @property
    def operational_logs(self) -> Tuple[EventRecord, ...]:
        return tuple(self._operational_logs)

    @property
    def audit_records(self) -> Tuple[EventRecord, ...]:
        return tuple(self._audit_records)

    def record_event(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        audit: bool = False,
        created_at: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> EventRecord:
        operational_record = self.append_operational_log(
            event_type,
            payload,
            created_at=created_at,
            event_id=event_id,
        )
        if audit:
            self.append_audit_record(
                event_type,
                payload,
                created_at=operational_record.created_at,
                event_id=operational_record.event_id,
            )
        return operational_record

    def append_operational_log(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        created_at: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> EventRecord:
        record = EventRecord(
            event_id=event_id or str(uuid.uuid4()),
            event_type=event_type,
            payload=self._freeze_payload(payload),
            created_at=self._timestamp(created_at),
        )
        self._operational_logs.append(record)
        return record

    def append_audit_record(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        created_at: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> EventRecord:
        event_payload = self._normalize_payload(payload)
        event_timestamp = self._timestamp(created_at)
        event_identifier = event_id or str(uuid.uuid4())
        digest = self._audit_digest(
            event_identifier,
            event_type,
            event_payload,
            event_timestamp,
        )
        record = EventRecord(
            event_id=event_identifier,
            event_type=event_type,
            payload=MappingProxyType(event_payload),
            created_at=event_timestamp,
            digest=digest,
        )
        self._audit_records.append(record)
        return record

    def cleanup_operational_logs(
        self,
        *,
        now: Optional[float] = None,
        retention_seconds: Optional[float] = None,
    ) -> int:
        retention = retention_seconds or self.operational_retention_seconds
        cutoff = self._timestamp(now) - retention
        before = len(self._operational_logs)
        self._operational_logs = [
            record
            for record in self._operational_logs
            if record.created_at >= cutoff
        ]
        return before - len(self._operational_logs)

    def cleanup_audit_records(
        self,
        *,
        now: Optional[float] = None,
    ) -> int:
        cutoff = self._timestamp(now) - self.audit_retention_seconds
        before = len(self._audit_records)
        self._audit_records = [
            record
            for record in self._audit_records
            if record.created_at >= cutoff
        ]
        return before - len(self._audit_records)

    def cleanup(self, *, now: Optional[float] = None) -> Dict[str, int]:
        return {
            "operational_logs": self.cleanup_operational_logs(now=now),
            "audit_records": self.cleanup_audit_records(now=now),
        }

    def _audit_digest(
        self,
        event_id: str,
        event_type: str,
        payload: Dict[str, Any],
        created_at: float,
    ) -> str:
        previous_digest = (
            self._audit_records[-1].digest if self._audit_records else None
        )
        digest_input = {
            "created_at": created_at,
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
            "previous_digest": previous_digest,
        }
        canonical = json.dumps(
            digest_input,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def _timestamp(self, value: Optional[float]) -> float:
        return self._clock() if value is None else value

    def _freeze_payload(
        self,
        payload: Optional[Dict[str, Any]],
    ) -> Mapping[str, Any]:
        return MappingProxyType(self._normalize_payload(payload))

    def _normalize_payload(
        self,
        payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return json.loads(
            json.dumps(payload or {}, sort_keys=True, default=str)
        )
