"""Run detail response shaping and access checks."""

import copy
import re
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

PUBLIC_RUN_FIELDS = (
    "run_id",
    "status",
    "agent_id",
    "created_at",
    "started_at",
    "finished_at",
    "result",
    "error",
)

ADMIN_RUN_FIELDS = (
    "tenant_id",
    "worker_id",
    "queue",
    "attempt",
    "trace_id",
)

ADMIN_SCOPE_VALUES = {"admin", "runs:admin", "run:admin"}
ADMIN_HEADER_VALUES = {"1", "true", "yes", "admin"}


class RunDetailValidationError(ValueError):
    """Raised when a run detail request is malformed."""


class RunDetailAuthorizationError(PermissionError):
    """Raised when admin-only run fields are requested without admin scope."""


class RunDetailNotFoundError(LookupError):
    """Raised when a run detail record does not exist."""


class AdminRunFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: Optional[str] = None
    worker_id: Optional[str] = None
    queue: Optional[str] = None
    attempt: Optional[int] = None
    trace_id: Optional[str] = None


class RunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    agent_id: Optional[str] = None
    created_at: Optional[float] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    admin: Optional[AdminRunFields] = None


def validate_run_id(run_id: str) -> str:
    """Return a normalized run id or reject it before any protected lookup."""

    candidate = (run_id or "").strip()
    if not RUN_ID_PATTERN.fullmatch(candidate):
        raise RunDetailValidationError("run_id is malformed")
    return candidate


def request_has_admin_run_scope(
    admin_header: Optional[str],
    scopes_header: Optional[str],
) -> bool:
    if admin_header and admin_header.strip().lower() in ADMIN_HEADER_VALUES:
        return True

    scopes = set()
    for raw_scope in (scopes_header or "").replace(",", " ").split():
        scopes.add(raw_scope.strip().lower())
    return bool(scopes & ADMIN_SCOPE_VALUES)


class RunDetailService:
    def __init__(
        self,
        initial_runs: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._runs: Dict[str, Dict[str, Any]] = {}
        for run_id, detail in (initial_runs or {}).items():
            self.store_run_detail(run_id, detail)

    def store_run_detail(self, run_id: str, detail: Dict[str, Any]) -> None:
        normalized_run_id = validate_run_id(run_id)
        record = copy.deepcopy(detail)
        record["run_id"] = normalized_run_id
        self._runs[normalized_run_id] = record

    def get_run_detail_response(
        self,
        run_id: str,
        include_admin_fields: bool = False,
        requester_is_admin: bool = False,
    ) -> Dict[str, Any]:
        normalized_run_id = validate_run_id(run_id)

        if include_admin_fields and not requester_is_admin:
            raise RunDetailAuthorizationError(
                "admin run fields require admin scope",
            )

        record = self._lookup_run(normalized_run_id)
        if record is None:
            raise RunDetailNotFoundError(normalized_run_id)

        return self._shape_response(record, include_admin_fields)

    def _lookup_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        record = self._runs.get(run_id)
        if record is None:
            return None
        return copy.deepcopy(record)

    def _shape_response(
        self,
        record: Dict[str, Any],
        include_admin_fields: bool,
    ) -> Dict[str, Any]:
        response = {
            "run_id": str(record["run_id"]),
            "status": str(record.get("status", "unknown")),
        }

        for field in PUBLIC_RUN_FIELDS:
            if field in {"run_id", "status"}:
                continue
            if field in record:
                response[field] = copy.deepcopy(record[field])

        if include_admin_fields:
            admin = {}
            for field in ADMIN_RUN_FIELDS:
                if field in record and record[field] is not None:
                    admin[field] = copy.deepcopy(record[field])
            if admin:
                response["admin"] = admin

        return response
