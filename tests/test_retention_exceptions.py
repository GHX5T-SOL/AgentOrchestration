from datetime import datetime, timedelta, timezone

import pytest

from src.common.retention_exceptions import (
    RetentionException,
    RetentionExceptionRegistry,
    RetentionExceptionValidationError,
)


NOW = datetime(2030, 5, 22, 5, 33, tzinfo=timezone.utc)


def test_retention_exception_requires_owner_reason_expiry_and_review_date():
    registry = RetentionExceptionRegistry()

    with pytest.raises(RetentionExceptionValidationError):
        registry.add(
            artifact_category="vectors",
            owner="",
            reason="legal hold review",
            expires_at=NOW + timedelta(days=7),
            review_at=NOW + timedelta(days=1),
        )

    with pytest.raises(RetentionExceptionValidationError):
        registry.add(
            artifact_category="vectors",
            owner="privacy-team",
            reason="",
            expires_at=NOW + timedelta(days=7),
            review_at=NOW + timedelta(days=1),
        )

    with pytest.raises(RetentionExceptionValidationError):
        registry.add(
            artifact_category="vectors",
            owner="privacy-team",
            reason="legal hold review",
            expires_at=datetime(2030, 5, 29),
            review_at=NOW + timedelta(days=1),
        )

    with pytest.raises(RetentionExceptionValidationError):
        registry.add(
            artifact_category="vectors",
            owner="privacy-team",
            reason="legal hold review",
            expires_at=NOW + timedelta(days=7),
            review_at=datetime(2030, 5, 23),
        )


def test_expired_exceptions_fail_governance_validation():
    expired = RetentionException.create(
        artifact_category="raw-payloads",
        owner="data-owner",
        reason="incident response preservation",
        expires_at=NOW - timedelta(minutes=1),
        review_at=NOW - timedelta(days=1),
        exception_id="expired-1",
        created_at=NOW - timedelta(days=3),
    )
    registry = RetentionExceptionRegistry([expired])

    with pytest.raises(
        RetentionExceptionValidationError,
        match="expired-1.*expired",
    ):
        registry.validate_governance(now=NOW)


def test_review_date_after_expiration_fails_governance_validation():
    invalid_review = RetentionException.create(
        artifact_category="embeddings",
        owner="ml-governance",
        reason="model rollback audit",
        expires_at=NOW + timedelta(days=5),
        review_at=NOW + timedelta(days=6),
        exception_id="bad-review",
        created_at=NOW,
    )
    registry = RetentionExceptionRegistry([invalid_review])

    with pytest.raises(
        RetentionExceptionValidationError,
        match="review is after expiry",
    ):
        registry.validate_governance(now=NOW)


def test_active_exception_report_groups_by_owner():
    registry = RetentionExceptionRegistry()
    registry.add(
        artifact_category="embeddings",
        owner="ml-governance",
        reason="rollback audit",
        expires_at=NOW + timedelta(days=5),
        review_at=NOW + timedelta(days=1),
        exception_id="ml-2",
    )
    registry.add(
        artifact_category="search-index",
        owner="search-team",
        reason="regulatory export hold",
        expires_at=NOW + timedelta(days=10),
        review_at=NOW + timedelta(days=2),
        exception_id="search-1",
    )
    registry.add(
        artifact_category="model-cache",
        owner="ml-governance",
        reason="customer deletion reconciliation",
        expires_at=NOW + timedelta(days=2),
        review_at=NOW + timedelta(days=1),
        exception_id="ml-1",
    )

    report = registry.active_report_by_owner(now=NOW)

    assert list(report) == ["ml-governance", "search-team"]
    assert [item["exception_id"] for item in report["ml-governance"]] == [
        "ml-1",
        "ml-2",
    ]
    assert report["ml-governance"][0]["artifact_category"] == "model-cache"
    assert report["search-team"][0]["reason"] == "regulatory export hold"
