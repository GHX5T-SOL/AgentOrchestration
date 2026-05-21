import base64
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from src.agent.registry import AgentRegistry
from src.api import routes
from src.api.server import create_app
from src.common.metrics import metrics


def make_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AO_AUTH_AUDIENCE", "agent-workers")
    monkeypatch.setenv("AO_REQUIRED_SCOPE", "agent:worker")
    monkeypatch.setenv("AO_JWT_SECRET", "test-secret")
    monkeypatch.setenv("AO_JWT_ISSUER", "agent-orchestrator")
    monkeypatch.setenv("AO_ALLOWED_ROLES", "worker,admin")
    monkeypatch.setenv("AO_REVOKED_JTIS", "revoked-token")
    routes.registry = AgentRegistry()
    return TestClient(create_app())


def make_token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "worker-service",
        "aud": "agent-workers",
        "scope": "agent:worker",
        "workspace_role": "worker",
        "iss": "agent-orchestrator",
        "jti": "valid-token",
        "nbf": now - 5,
        "exp": now + 300,
    }
    claims.update(overrides)
    unsigned = ".".join([
        _encode({"alg": "HS256", "typ": "JWT"}),
        _encode(claims),
    ])
    signature = hmac.new(
        b"test-secret",
        unsigned.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{unsigned}.{_encode_bytes(signature)}"


def _encode(value: dict) -> str:
    return _encode_bytes(json.dumps(value).encode("utf-8"))


def _encode_bytes(value: bytes) -> str:
    encoded = base64.urlsafe_b64encode(value)
    return encoded.decode("ascii").rstrip("=")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def metric_count(name: str) -> int:
    return metrics.snapshot()["counters"].get(name, 0)


def test_anonymous_and_malformed_principals_are_denied(monkeypatch):
    client = make_client(monkeypatch)

    anonymous = client.get("/api/v2/agents")
    malformed = client.get(
        "/api/v2/agents",
        headers=bearer("not-a-jwt"),
    )

    assert anonymous.status_code == 401
    assert anonymous.headers["x-auth-decision"] == "denied"
    assert malformed.status_code == 401
    assert malformed.headers["x-auth-decision"] == "denied"


def test_stale_revoked_and_future_tokens_do_not_leak_token(monkeypatch):
    client = make_client(monkeypatch)
    expired = make_token(exp=int(time.time()) - 1)
    not_active = make_token(nbf=int(time.time()) + 60)
    revoked = make_token(jti="revoked-token")

    expired_response = client.get("/api/v2/agents", headers=bearer(expired))
    not_active_response = client.get(
        "/api/v2/agents",
        headers=bearer(not_active),
    )
    revoked_response = client.get("/api/v2/agents", headers=bearer(revoked))

    assert expired_response.status_code == 401
    assert not_active_response.status_code == 401
    assert revoked_response.status_code == 401
    assert expired not in expired_response.text
    assert not_active not in not_active_response.text
    assert revoked not in revoked_response.text
    assert expired_response.headers["x-auth-decision"] == "denied"
    assert not_active_response.headers["x-auth-decision"] == "denied"
    assert revoked_response.headers["x-auth-decision"] == "denied"


def test_wrong_audience_issuer_scope_and_role_are_denied(monkeypatch):
    client = make_client(monkeypatch)

    wrong_audience = client.get(
        "/api/v2/agents",
        headers=bearer(make_token(aud="browser-client")),
    )
    wrong_issuer = client.get(
        "/api/v2/agents",
        headers=bearer(make_token(iss="browser-gateway")),
    )
    wrong_scope = client.get(
        "/api/v2/agents",
        headers=bearer(make_token(scope="agent:read")),
    )
    wrong_role = client.get(
        "/api/v2/agents",
        headers=bearer(make_token(workspace_role="viewer")),
    )

    assert wrong_audience.status_code == 403
    assert wrong_issuer.status_code == 403
    assert wrong_scope.status_code == 403
    assert wrong_role.status_code == 403
    assert wrong_audience.headers["x-auth-decision"] == "denied"
    assert wrong_issuer.headers["x-auth-decision"] == "denied"
    assert wrong_scope.headers["x-auth-decision"] == "denied"
    assert wrong_role.headers["x-auth-decision"] == "denied"


def test_authorized_service_token_completes_protected_workflow(monkeypatch):
    client = make_client(monkeypatch)
    headers = bearer(make_token(aud=["agent-workers", "metrics"]))

    response = client.post(
        "/api/v2/agents",
        params={"name": "agent-one", "agent_type": "worker.processor"},
        headers=headers,
    )
    agents = client.get("/api/v2/agents", headers=headers)

    assert response.status_code == 200
    assert response.headers["x-auth-decision"] == "accepted"
    assert response.json()["status"] == "registered"
    assert agents.status_code == 200
    assert len(agents.json()["agents"]) == 1


def test_auth_decision_metrics_are_recorded(monkeypatch):
    client = make_client(monkeypatch)
    accepted_before = metric_count("auth.accepted")
    denied_before = metric_count("auth.denied")
    wrong_audience_before = metric_count("auth.denied.wrong_audience")

    accepted = client.get("/api/v2/agents", headers=bearer(make_token()))
    denied = client.get(
        "/api/v2/agents",
        headers=bearer(make_token(aud="browser-client")),
    )

    assert accepted.status_code == 200
    assert denied.status_code == 403
    assert metric_count("auth.accepted") == accepted_before + 1
    assert metric_count("auth.denied") == denied_before + 1
    assert metric_count("auth.denied.wrong_audience") == (
        wrong_audience_before + 1
    )


def test_browser_session_cookie_uses_same_audience_policy(monkeypatch):
    client = make_client(monkeypatch)
    client.cookies.set("ao_session", make_token())

    response = client.get("/api/v2/agents")

    assert response.status_code == 200
    assert response.headers["x-auth-decision"] == "accepted"
    assert response.json() == {"agents": []}
