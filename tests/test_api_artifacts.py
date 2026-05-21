from fastapi.testclient import TestClient

from src.api import routes
from src.api.artifacts import (
    ArtifactIngestionService,
    MAX_ARTIFACT_BODY_BYTES,
)
from src.api.server import create_app


def setup_function():
    routes.artifact_service = ArtifactIngestionService()


def test_authorized_artifact_upload_commits_metadata():
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/runs/run-1/artifacts/result.json",
        content=b'{"ok": true}',
        headers={
            "Authorization": "Bearer test-token",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["artifact"]["run_id"] == "run-1"
    assert body["artifact"]["artifact_name"] == "result.json"
    assert body["artifact"]["size"] == len(b'{"ok": true}')
    assert routes.artifact_service.count() == 1


def test_unauthorized_artifact_upload_is_rejected_before_mutation():
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/runs/run-1/artifacts/result.json",
        content=b"artifact",
    )

    assert response.status_code == 401
    assert routes.artifact_service.count() == 0


def test_artifact_upload_rejects_declared_oversized_body_before_mutation():
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/runs/run-1/artifacts/result.json",
        content=b"short",
        headers={
            "Authorization": "Bearer test-token",
            "content-length": str(MAX_ARTIFACT_BODY_BYTES + 1),
        },
    )

    assert response.status_code == 413
    assert routes.artifact_service.count() == 0


def test_artifact_upload_rejects_actual_oversized_body_before_mutation():
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/runs/run-1/artifacts/result.json",
        content=b"x" * (MAX_ARTIFACT_BODY_BYTES + 1),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 413
    assert routes.artifact_service.count() == 0


def test_artifact_upload_rejects_malformed_identifier_before_mutation():
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/runs/bad!run/artifacts/result.json",
        content=b"artifact",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert routes.artifact_service.count() == 0
