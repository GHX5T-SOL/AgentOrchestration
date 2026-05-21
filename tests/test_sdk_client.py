import pytest

from src.sdk.client import OrchestratorClient


class RecordingClient(OrchestratorClient):
    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="test-key")
        self.requests = []

    def _request(self, method, path, data=None):
        self.requests.append((method, path, data))
        return {"ok": True}


def test_register_agent_rejects_blank_names_before_post():
    client = RecordingClient()

    with pytest.raises(ValueError, match="Agent name cannot be blank"):
        client.register_agent("   ", "worker.processor")

    assert client.requests == []


def test_register_agent_trims_valid_names_before_payload():
    client = RecordingClient()

    response = client.register_agent("  worker-one  ", "worker.processor")

    assert response == {"ok": True}
    assert client.requests == [
        (
            "POST",
            "/agents",
            {
                "name": "worker-one",
                "agent_type": "worker.processor",
                "config": {},
            },
        )
    ]
