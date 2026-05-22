import pytest

from src.common.collaboration_auth import (
    CollaborationAuthError,
    CollaborationPrincipal,
    SavedView,
    SavedViewSharingService,
    WorkspaceMembership,
)


def make_service(
    *,
    actor_role="editor",
    actor_version=1,
    actor_active=True,
    actor_disabled=False,
    actor_revoked=False,
    target_workspace="workspace-a",
):
    memberships = {
        "actor": WorkspaceMembership(
            user_id="actor",
            workspace_id="workspace-a",
            role=actor_role,
            version=actor_version,
            active=actor_active,
            disabled=actor_disabled,
            revoked=actor_revoked,
        ),
        "target": WorkspaceMembership(
            user_id="target",
            workspace_id=target_workspace,
            role="viewer",
        ),
    }
    views = {
        "view-a": SavedView(
            view_id="view-a",
            workspace_id="workspace-a",
            owner_id="actor",
        )
    }
    return SavedViewSharingService(views, memberships)


def make_principal(**overrides):
    values = {
        "user_id": "actor",
        "workspace_id": "workspace-a",
        "role": "editor",
        "membership_version": 1,
        "client_type": "browser",
    }
    values.update(overrides)
    return CollaborationPrincipal(**values)


@pytest.mark.parametrize("client_type", ["browser", "token"])
def test_authorized_workspace_member_can_share_saved_view(client_type):
    service = make_service()
    principal = make_principal(client_type=client_type)

    view = service.share_view(principal, "view-a", "target", "editor")

    assert view.shares["target"] == "editor"


def test_anonymous_principal_cannot_share_saved_view():
    service = make_service()

    with pytest.raises(CollaborationAuthError, match="anonymous"):
        service.share_view(None, "view-a", "target")


def test_stale_membership_version_is_denied():
    service = make_service(actor_version=2)
    principal = make_principal(membership_version=1)

    with pytest.raises(CollaborationAuthError, match="stale membership"):
        service.share_view(principal, "view-a", "target")


def test_revoked_membership_is_denied():
    service = make_service(actor_revoked=True)
    principal = make_principal()

    with pytest.raises(CollaborationAuthError, match="inactive"):
        service.share_view(principal, "view-a", "target")


def test_disabled_principal_is_denied_before_saved_view_share():
    service = make_service()
    principal = make_principal(disabled=True)

    with pytest.raises(CollaborationAuthError, match="inactive principal"):
        service.share_view(principal, "view-a", "target")


def test_expired_or_malformed_principal_is_denied():
    service = make_service()

    for principal in (
        make_principal(expired=True),
        make_principal(malformed=True),
    ):
        with pytest.raises(CollaborationAuthError, match="stale or malformed"):
            service.share_view(principal, "view-a", "target")


def test_insufficient_role_cannot_share_saved_view():
    service = make_service(actor_role="viewer")
    principal = make_principal(role="viewer")

    with pytest.raises(CollaborationAuthError, match="insufficient role"):
        service.share_view(principal, "view-a", "target")


def test_saved_view_workspace_must_match_current_principal_workspace():
    service = make_service()
    principal = make_principal(workspace_id="workspace-b")

    with pytest.raises(CollaborationAuthError, match="outside principal"):
        service.share_view(principal, "view-a", "target")


def test_target_membership_must_belong_to_saved_view_workspace():
    service = make_service(target_workspace="workspace-b")
    principal = make_principal()

    with pytest.raises(CollaborationAuthError, match="target is outside"):
        service.share_view(principal, "view-a", "target")
