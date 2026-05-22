from fastapi.testclient import TestClient

from src.api.server import create_app


class TestPublicApiClientValidation:
    def setup_method(self):
        self.client = TestClient(create_app())
        self.headers = {"Authorization": "Bearer test-token"}

    def test_malformed_name_returns_consistent_validation_error(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "   ", "agent_type": "worker"},
            headers=self.headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]["error_code"] == "VALIDATION_INVALID_NAME"

    def test_invalid_agent_type_returns_consistent_validation_error(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "demo-agent", "agent_type": "unknown"},
            headers=self.headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert body["detail"]["error_code"] == "VALIDATION_INVALID_AGENT_TYPE"

    def test_authorized_valid_request_succeeds(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "demo-agent", "agent_type": "worker"},
            headers=self.headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "registered"
        assert body["agent_id"]

    def test_unauthorized_request_is_rejected_before_mutation(self):
        response = self.client.post(
            "/api/v2/agents",
            params={"name": "demo-agent", "agent_type": "worker"},
        )
        assert response.status_code == 401
