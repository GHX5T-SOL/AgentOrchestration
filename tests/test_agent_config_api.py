from fastapi.testclient import TestClient

from src.agent.registry import AgentRegistry
from src.api import routes
from src.api.server import create_app


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def make_client() -> TestClient:
    routes.registry = AgentRegistry()
    return TestClient(create_app())


def register_agent(client: TestClient) -> str:
    response = client.post(
        "/api/v2/agents",
        params={"name": "test-agent", "agent_type": "worker.processor"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    return response.json()["agent_id"]


def current_config_etag(client: TestClient, agent_id: str) -> str:
    response = client.get(f"/api/v2/agents/{agent_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    return response.headers["etag"]


def test_authorized_config_update_requires_current_etag():
    client = make_client()
    agent_id = register_agent(client)
    etag = current_config_etag(client, agent_id)

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"config": {"memory": "8Gi", "priority": "high"}},
        headers={**AUTH_HEADERS, "If-Match": etag},
    )

    assert response.status_code == 200
    assert response.json() == {
        "agent_id": agent_id,
        "config": {"memory": "8Gi", "priority": "high"},
    }
    assert response.headers["etag"] != etag

    agent = client.get(f"/api/v2/agents/{agent_id}", headers=AUTH_HEADERS)
    assert agent.json()["config"] == {"memory": "8Gi", "priority": "high"}
    assert agent.headers["etag"] == response.headers["etag"]


def test_stale_etag_rejected_without_overwriting_newer_config():
    client = make_client()
    agent_id = register_agent(client)
    original_etag = current_config_etag(client, agent_id)

    first_update = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"config": {"revision": 1}},
        headers={**AUTH_HEADERS, "If-Match": original_etag},
    )
    assert first_update.status_code == 200

    stale_update = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"config": {"revision": 0}},
        headers={**AUTH_HEADERS, "If-Match": original_etag},
    )

    assert stale_update.status_code == 412
    agent = client.get(f"/api/v2/agents/{agent_id}", headers=AUTH_HEADERS)
    assert agent.json()["config"] == {"revision": 1}


def test_missing_or_malformed_precondition_rejected_before_lookup():
    client = make_client()

    missing_etag = client.put(
        "/api/v2/agents/missing-agent/config",
        json={"config": {"enabled": True}},
        headers=AUTH_HEADERS,
    )
    assert missing_etag.status_code == 428

    malformed_etag = client.put(
        "/api/v2/agents/missing-agent/config",
        json={"config": {"enabled": True}},
        headers={**AUTH_HEADERS, "If-Match": "not-an-etag"},
    )
    assert malformed_etag.status_code == 400


def test_malformed_config_body_rejected_before_lookup():
    client = make_client()

    response = client.put(
        "/api/v2/agents/missing-agent/config",
        json=["not", "an", "object"],
        headers={**AUTH_HEADERS, "If-Match": '"config-1"'},
    )

    assert response.status_code == 400


def test_unknown_agent_with_valid_precondition_returns_not_found():
    client = make_client()

    response = client.put(
        "/api/v2/agents/missing-agent/config",
        json={"config": {"enabled": True}},
        headers={**AUTH_HEADERS, "If-Match": '"config-1"'},
    )

    assert response.status_code == 404


def test_unauthorized_config_update_is_rejected():
    client = make_client()
    agent_id = register_agent(client)

    response = client.put(
        f"/api/v2/agents/{agent_id}/config",
        json={"config": {"enabled": False}},
        headers={"If-Match": current_config_etag(client, agent_id)},
    )

    assert response.status_code == 401
