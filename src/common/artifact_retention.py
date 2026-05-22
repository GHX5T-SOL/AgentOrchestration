"""Hold-aware artifact retention cleanup planning."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ArtifactRetentionRecord:
    artifact_id: str
    project_id: str
    retention_expires_at: datetime
    legal_hold: bool = False
    investigation_hold: bool = False
    hold_reason: Optional[str] = None

    @property
    def active_holds(self) -> Tuple[str, ...]:
        holds: List[str] = []
        if self.legal_hold:
            holds.append("legal")
        if self.investigation_hold:
            holds.append("investigation")
        return tuple(holds)


@dataclass(frozen=True)
class RetentionCleanupPlan:
    deletable_artifact_ids: List[str]
    held_expired_artifacts: List[Dict[str, object]]


class ArtifactRetentionPlanner:
    """Build deletion candidates without deleting held artifacts."""

    def plan_cleanup(
        self,
        records: Iterable[ArtifactRetentionRecord],
        *,
        now: datetime,
    ) -> RetentionCleanupPlan:
        deletable: List[str] = []
        held_report: List[Dict[str, object]] = []

        for record in sorted(records, key=lambda item: item.artifact_id):
            if record.retention_expires_at > now:
                continue

            active_holds = record.active_holds
            if active_holds:
                held_report.append(
                    {
                        "artifact_id": record.artifact_id,
                        "project_id": record.project_id,
                        "retention_expires_at": (
                            record.retention_expires_at.isoformat()
                        ),
                        "active_holds": list(active_holds),
                        "hold_reason": record.hold_reason or "",
                    }
                )
                continue

            deletable.append(record.artifact_id)

        return RetentionCleanupPlan(
            deletable_artifact_ids=deletable,
            held_expired_artifacts=held_report,
        )


def deletion_candidates(
    records: Iterable[ArtifactRetentionRecord],
    *,
    now: datetime,
) -> List[str]:
    plan = ArtifactRetentionPlanner().plan_cleanup(records, now=now)
    return plan.deletable_artifact_ids
