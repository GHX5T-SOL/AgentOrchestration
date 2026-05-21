"""Artifact ingestion guards and storage."""

import hashlib
import re
import time
from typing import Any, Dict

MAX_ARTIFACT_BODY_BYTES = 1024 * 1024
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ArtifactValidationError(ValueError):
    pass


class ArtifactTooLargeError(ArtifactValidationError):
    pass


class ArtifactIngestionService:
    def __init__(self, max_body_bytes: int = MAX_ARTIFACT_BODY_BYTES):
        self.max_body_bytes = max_body_bytes
        self._artifacts: Dict[str, Dict[str, Any]] = {}

    def ingest(
        self,
        run_id: str,
        artifact_name: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        run_id = self._validate_identifier(run_id, "run_id")
        artifact_name = self._validate_identifier(
            artifact_name,
            "artifact_name",
        )
        body = self._validate_body(body)

        key = f"{run_id}:{artifact_name}"
        record = {
            "run_id": run_id,
            "artifact_name": artifact_name,
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": content_type,
            "created_at": time.time(),
        }
        self._artifacts[key] = record
        return dict(record)

    def get(self, run_id: str, artifact_name: str) -> Dict[str, Any]:
        key = f"{run_id}:{artifact_name}"
        return dict(self._artifacts[key])

    def count(self) -> int:
        return len(self._artifacts)

    def _validate_identifier(self, value: str, field: str) -> str:
        if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
            raise ArtifactValidationError(f"invalid {field}")
        return value

    def _validate_body(self, body: bytes) -> bytes:
        if not isinstance(body, bytes):
            raise ArtifactValidationError("artifact body must be bytes")
        if not body:
            raise ArtifactValidationError("artifact body is required")
        if len(body) > self.max_body_bytes:
            raise ArtifactTooLargeError("artifact body exceeds max size")
        return body
