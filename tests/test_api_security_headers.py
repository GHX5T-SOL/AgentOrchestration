from fastapi import APIRouter
from fastapi.testclient import TestClient

from src.api.middleware import SECURITY_HEADERS
from src.api.server import create_app


def _assert_security_headers(response):
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_security_headers_are_added_to_normal_responses():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    _assert_security_headers(response)


def test_security_headers_are_added_to_rejected_responses():
    client = TestClient(create_app())

    response = client.get("/api/v2/agents")

    assert response.status_code == 401
    _assert_security_headers(response)


def test_security_headers_are_added_to_exception_responses():
    app = create_app()
    router = APIRouter()

    @router.get("/explode")
    async def explode():
        raise RuntimeError("secret-token")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/explode")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers["X-Error-Sanitized"] == "true"
    assert "secret-token" not in response.text
    _assert_security_headers(response)


def test_exception_logging_omits_sensitive_exception_details(caplog):
    app = create_app()
    router = APIRouter()

    @router.get("/explode")
    async def explode():
        raise RuntimeError("secret-token")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/explode?token=secret-query")

    assert response.status_code == 500
    assert "secret-token" not in caplog.text
    assert "secret-query" not in caplog.text
