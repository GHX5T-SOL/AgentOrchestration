import pytest
from fastapi.testclient import TestClient

from src.api.auth import Principal, TokenAuthProvider
from src.api.server import create_app


def _headers(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    provider = TokenAuthProvider(
        tokens={
            "viewer": Principal(
                subject="viewer-user",
                workspace_id="workspace-a",
                role="viewer",
                scopes={"agents:read"},
            ),
            "operator": Principal(
                subject="operator-user",
                workspace_id="workspace-a",
                role="operator",
                scopes={"agents:read", "agents:write"},
            ),
            "write-scope-viewer": Principal(
                subject="scope-only-user",
                workspace_id="workspace-a",
                role="viewer",
                scopes={"agents:write"},
            ),
            "no-scope": Principal(
                subject="limited-user",
                workspace_id="workspace-a",
                role="operator",
                scopes=set(),
            ),
            "revoked": Principal(
                subject="revoked-user",
                workspace_id="workspace-a",
                role="admin",
                scopes={"*"},
                revoked=True,
            ),
            "stale": Principal(
                subject="stale-user",
                workspace_id="workspace-a",
                role="admin",
                scopes={"*"},
                membership_version=1,
            ),
        },
        current_memberships={("stale-user", "workspace-a"): 2},
    )
    return TestClient(create_app({"auth_provider": provider}))


def test_trailing_slash_redirect_is_auth_guarded_before_redirect(client):
    response = client.get("/api/v2/agents/", follow_redirects=False)

    assert response.status_code == 401
    assert "location" not in response.headers


@pytest.mark.parametrize(
    ("token", "expected_status"),
    [
        ("unknown", 401),
        ("revoked", 401),
        ("stale", 401),
        ("no-scope", 403),
    ],
)
def test_invalid_stale_revoked_and_insufficient_scope_denied(
    client, token, expected_status
):
    response = client.get("/api/v2/agents", headers=_headers(token))

    assert response.status_code == expected_status


def test_insufficient_workspace_role_denied_before_mutation(client):
    response = client.post(
        "/api/v2/agents",
        params={"name": "denied-agent", "agent_type": "worker.processor"},
        headers=_headers("write-scope-viewer"),
    )

    assert response.status_code == 403


def test_authorized_workspace_operator_can_complete_agent_workflow(client):
    create_response = client.post(
        "/api/v2/agents",
        params={"name": "authz-agent", "agent_type": "worker.processor"},
        headers=_headers("operator"),
    )
    assert create_response.status_code == 200

    agent_id = create_response.json()["agent_id"]
    start_response = client.post(
        f"/api/v2/agents/{agent_id}/start",
        headers=_headers("operator"),
    )
    assert start_response.status_code == 200

    read_response = client.get(
        f"/api/v2/agents/{agent_id}",
        headers=_headers("operator"),
    )
    assert read_response.status_code == 200
    assert read_response.json()["status"] == "running"


def test_viewer_can_read_but_not_write(client):
    read_response = client.get("/api/v2/agents", headers=_headers("viewer"))
    assert read_response.status_code == 200

    write_response = client.post(
        "/api/v2/agents",
        params={"name": "viewer-write", "agent_type": "worker.processor"},
        headers=_headers("viewer"),
    )
    assert write_response.status_code == 403
