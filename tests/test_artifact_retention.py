from datetime import datetime, timedelta, timezone

from src.common.artifact_retention import (
    ArtifactRetentionPlanner,
    ArtifactRetentionRecord,
    deletion_candidates,
)


NOW = datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc)


def artifact(
    artifact_id,
    *,
    expired=True,
    legal_hold=False,
    investigation_hold=False,
    hold_reason=None,
):
    expires_at = (
        NOW - timedelta(days=1) if expired else NOW + timedelta(days=1)
    )
    return ArtifactRetentionRecord(
        artifact_id=artifact_id,
        project_id="research-project",
        retention_expires_at=expires_at,
        legal_hold=legal_hold,
        investigation_hold=investigation_hold,
        hold_reason=hold_reason,
    )


def test_cleanup_deletes_only_expired_artifacts_without_holds():
    plan = ArtifactRetentionPlanner().plan_cleanup(
        [
            artifact("expired-unheld"),
            artifact("future-unheld", expired=False),
            artifact("expired-legal-hold", legal_hold=True),
            artifact("expired-investigation-hold", investigation_hold=True),
        ],
        now=NOW,
    )

    assert plan.deletable_artifact_ids == ["expired-unheld"]


def test_held_expired_artifacts_are_reported_without_being_deletable():
    plan = ArtifactRetentionPlanner().plan_cleanup(
        [
            artifact(
                "legal",
                legal_hold=True,
                hold_reason="active litigation",
            ),
            artifact("investigation", investigation_hold=True),
            artifact(
                "both",
                legal_hold=True,
                investigation_hold=True,
                hold_reason="regulatory review",
            ),
        ],
        now=NOW,
    )

    assert plan.deletable_artifact_ids == []
    assert [item["artifact_id"] for item in plan.held_expired_artifacts] == [
        "both",
        "investigation",
        "legal",
    ]
    assert plan.held_expired_artifacts[0]["active_holds"] == [
        "legal",
        "investigation",
    ]
    assert plan.held_expired_artifacts[0]["hold_reason"] == "regulatory review"


def test_held_expired_report_uses_bounded_metadata():
    plan = ArtifactRetentionPlanner().plan_cleanup(
        [artifact("held", legal_hold=True, hold_reason="legal hold")],
        now=NOW,
    )

    assert plan.held_expired_artifacts == [
        {
            "artifact_id": "held",
            "project_id": "research-project",
            "retention_expires_at": (NOW - timedelta(days=1)).isoformat(),
            "active_holds": ["legal"],
            "hold_reason": "legal hold",
        }
    ]


def test_deletion_candidates_helper_matches_planner():
    records = [
        artifact("delete-me"),
        artifact("keep-me", legal_hold=True),
    ]

    assert deletion_candidates(records, now=NOW) == ["delete-me"]
