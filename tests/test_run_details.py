from fastapi.testclient import TestClient

from src.api import routes
from src.api.run_details import RunDetailService
from src.api.server import create_app


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


class CountingRunDetailService(RunDetailService):
    def __init__(self, initial_runs=None):
        super().__init__(initial_runs)
        self.lookup_count = 0

    def _lookup_run(self, run_id):
        self.lookup_count += 1
        return super()._lookup_run(run_id)


def build_client(monkeypatch, service):
    monkeypatch.setattr(routes, "run_detail_service", service)
    return TestClient(create_app())


def run_record():
    return {
        "status": "completed",
        "agent_id": "agent-1",
        "started_at": 100.0,
        "finished_at": 105.0,
        "result": {"ok": True},
        "tenant_id": "tenant-a",
        "worker_id": "worker-7",
        "queue": "critical",
        "attempt": 2,
        "trace_id": "trace-123",
        "secret_ref": "vault://internal-token",
        "internal_notes": "do not expose",
    }


def test_run_detail_public_response_excludes_admin_fields(monkeypatch):
    service = CountingRunDetailService({"run-1": run_record()})
    client = build_client(monkeypatch, service)

    response = client.get("/api/v2/runs/run-1", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert service.lookup_count == 1
    body = response.json()
    assert body["run_id"] == "run-1"
    assert body["status"] == "completed"
    assert body["result"] == {"ok": True}
    assert "admin" not in body
    assert "tenant_id" not in body
    assert "secret_ref" not in body
    assert "internal_notes" not in body


def test_run_detail_admin_response_uses_admin_model(monkeypatch):
    service = CountingRunDetailService({"run-1": run_record()})
    client = build_client(monkeypatch, service)
    headers = {**AUTH_HEADERS, "X-Admin": "true"}

    response = client.get(
        "/api/v2/runs/run-1?include_admin=true",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["admin"] == {
        "tenant_id": "tenant-a",
        "worker_id": "worker-7",
        "queue": "critical",
        "attempt": 2,
        "trace_id": "trace-123",
    }
    assert "secret_ref" not in body["admin"]
    assert "internal_notes" not in body["admin"]


def test_run_detail_rejects_admin_fields_before_lookup(monkeypatch):
    service = CountingRunDetailService({"run-1": run_record()})
    client = build_client(monkeypatch, service)

    response = client.get(
        "/api/v2/runs/run-1?include_admin=true",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin run fields require admin scope"
    assert service.lookup_count == 0


def test_run_detail_rejects_malformed_run_id_before_lookup(monkeypatch):
    service = CountingRunDetailService({"run-1": run_record()})
    client = build_client(monkeypatch, service)

    response = client.get("/api/v2/runs/bad%20id", headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert response.json()["detail"] == "run_id is malformed"
    assert service.lookup_count == 0


def test_run_detail_requires_bearer_auth_before_route_lookup(monkeypatch):
    service = CountingRunDetailService({"run-1": run_record()})
    client = build_client(monkeypatch, service)

    response = client.get("/api/v2/runs/run-1")

    assert response.status_code == 401
    assert service.lookup_count == 0
