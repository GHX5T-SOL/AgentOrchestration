"""Collaboration authorization helpers for saved view sharing."""

from dataclasses import dataclass, field
from typing import Dict, Mapping, MutableMapping, Optional, Set


class CollaborationAuthError(PermissionError):
    """Raised when a collaboration action fails authorization."""


SHARE_ROLES: Set[str] = {"owner", "admin", "editor"}
VALID_CLIENT_TYPES: Set[str] = {"browser", "token"}


@dataclass(frozen=True)
class CollaborationPrincipal:
    user_id: str
    workspace_id: str
    role: str
    membership_version: int
    client_type: str
    authenticated: bool = True
    disabled: bool = False
    revoked: bool = False
    expired: bool = False
    malformed: bool = False


@dataclass(frozen=True)
class WorkspaceMembership:
    user_id: str
    workspace_id: str
    role: str
    version: int = 1
    active: bool = True
    disabled: bool = False
    revoked: bool = False


@dataclass
class SavedView:
    view_id: str
    workspace_id: str
    owner_id: str
    shares: MutableMapping[str, str] = field(default_factory=dict)


class CollaborationAuthorizer:
    """Authorize saved-view collaboration actions from current membership."""

    def __init__(self, memberships: Mapping[str, WorkspaceMembership]):
        self._memberships = dict(memberships)

    def require_saved_view_share(
        self,
        principal: Optional[CollaborationPrincipal],
        view: SavedView,
        target_membership: WorkspaceMembership,
    ) -> None:
        if principal is None or not principal.authenticated:
            raise CollaborationAuthError("anonymous principal")
        if principal.client_type not in VALID_CLIENT_TYPES:
            raise CollaborationAuthError("unsupported client type")
        if principal.disabled or principal.revoked:
            raise CollaborationAuthError("inactive principal")
        if principal.expired or principal.malformed:
            raise CollaborationAuthError("stale or malformed principal")
        if principal.workspace_id != view.workspace_id:
            raise CollaborationAuthError("view is outside principal workspace")

        current = self._memberships.get(principal.user_id)
        if current is None:
            raise CollaborationAuthError("missing membership")
        self._require_current_membership(principal, current)

        if current.role not in SHARE_ROLES:
            raise CollaborationAuthError("insufficient role")
        if target_membership.workspace_id != view.workspace_id:
            raise CollaborationAuthError("target is outside view workspace")
        if not target_membership.active or target_membership.revoked:
            raise CollaborationAuthError("target membership inactive")

    @staticmethod
    def _require_current_membership(
        principal: CollaborationPrincipal,
        current: WorkspaceMembership,
    ) -> None:
        if current.workspace_id != principal.workspace_id:
            raise CollaborationAuthError("workspace membership mismatch")
        if not current.active or current.disabled or current.revoked:
            raise CollaborationAuthError("current membership inactive")
        if current.version != principal.membership_version:
            raise CollaborationAuthError("stale membership")
        if current.role != principal.role:
            raise CollaborationAuthError("stale role")


class SavedViewSharingService:
    """Share saved views only after collaboration membership checks."""

    def __init__(
        self,
        views: Mapping[str, SavedView],
        memberships: Mapping[str, WorkspaceMembership],
    ):
        self._views: Dict[str, SavedView] = dict(views)
        self._memberships: Dict[str, WorkspaceMembership] = dict(memberships)
        self._authorizer = CollaborationAuthorizer(self._memberships)

    def share_view(
        self,
        principal: Optional[CollaborationPrincipal],
        view_id: str,
        target_user_id: str,
        access: str = "viewer",
    ) -> SavedView:
        view = self._views.get(view_id)
        if view is None:
            raise KeyError(view_id)
        target_membership = self._memberships.get(target_user_id)
        if target_membership is None:
            raise CollaborationAuthError("target membership missing")

        self._authorizer.require_saved_view_share(
            principal,
            view,
            target_membership,
        )
        view.shares[target_user_id] = access
        return view
