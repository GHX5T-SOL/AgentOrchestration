"""Retention exception governance metadata and reporting."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
from uuid import uuid4


class RetentionExceptionValidationError(ValueError):
    """Raised when a retention exception violates governance policy."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_timezone(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RetentionExceptionValidationError(
            f"{field_name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _require_text(value: Optional[str], field_name: str) -> str:
    if value is None or not value.strip():
        raise RetentionExceptionValidationError(f"{field_name} is required")
    return value.strip()


@dataclass(frozen=True)
class RetentionException:
    artifact_category: str
    owner: str
    reason: str
    expires_at: datetime
    review_at: datetime
    exception_id: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        artifact_category: str,
        owner: str,
        reason: str,
        expires_at: datetime,
        review_at: datetime,
        exception_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> "RetentionException":
        created = created_at or _utc_now()
        return cls(
            artifact_category=_require_text(
                artifact_category, "artifact_category"
            ),
            owner=_require_text(owner, "owner"),
            reason=_require_text(reason, "reason"),
            expires_at=_require_timezone(expires_at, "expires_at"),
            review_at=_require_timezone(review_at, "review_at"),
            exception_id=exception_id or str(uuid4()),
            created_at=_require_timezone(created, "created_at"),
        )

    def validate(self, now: Optional[datetime] = None) -> None:
        effective_now = _require_timezone(now or _utc_now(), "now")
        _require_text(self.artifact_category, "artifact_category")
        _require_text(self.owner, "owner")
        _require_text(self.reason, "reason")
        _require_timezone(self.expires_at, "expires_at")
        _require_timezone(self.review_at, "review_at")

        if self.expires_at <= effective_now:
            raise RetentionExceptionValidationError(
                f"retention exception {self.exception_id} has expired"
            )
        if self.review_at > self.expires_at:
            raise RetentionExceptionValidationError(
                f"retention exception {self.exception_id} review is after "
                "expiry"
            )


class RetentionExceptionRegistry:
    def __init__(
        self,
        exceptions: Optional[Iterable[RetentionException]] = None,
    ):
        self._exceptions: Dict[str, RetentionException] = {}
        for exception in exceptions or ():
            self._exceptions[exception.exception_id] = exception

    def add(
        self,
        artifact_category: str,
        owner: str,
        reason: str,
        expires_at: datetime,
        review_at: datetime,
        exception_id: Optional[str] = None,
    ) -> RetentionException:
        exception = RetentionException.create(
            artifact_category=artifact_category,
            owner=owner,
            reason=reason,
            expires_at=expires_at,
            review_at=review_at,
            exception_id=exception_id,
        )
        exception.validate()
        self._exceptions[exception.exception_id] = exception
        return exception

    def validate_governance(
        self, now: Optional[datetime] = None
    ) -> List[RetentionException]:
        exceptions = list(self._exceptions.values())
        for exception in exceptions:
            exception.validate(now=now)
        return exceptions

    def active_report_by_owner(
        self, now: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, str]]]:
        effective_now = _require_timezone(now or _utc_now(), "now")
        report: Dict[str, List[Dict[str, str]]] = {}
        for exception in self._exceptions.values():
            exception.validate(now=effective_now)
            report.setdefault(exception.owner, []).append(
                {
                    "exception_id": exception.exception_id,
                    "artifact_category": exception.artifact_category,
                    "reason": exception.reason,
                    "expires_at": exception.expires_at.isoformat(),
                    "review_at": exception.review_at.isoformat(),
                }
            )

        for owner_exceptions in report.values():
            owner_exceptions.sort(
                key=lambda item: (item["expires_at"], item["exception_id"])
            )
        return dict(sorted(report.items()))
