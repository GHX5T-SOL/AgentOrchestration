"""Shared API service helpers."""

from typing import Optional

ALLOWED_AGENT_TYPES = {"worker", "supervisor", "tool"}


class ApiValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_agent_registration(name: str, agent_type: str) -> None:
    if name is None or not str(name).strip():
        raise ApiValidationError(
            "VALIDATION_INVALID_NAME",
            "Agent name is required",
        )
    if agent_type is None or not str(agent_type).strip():
        raise ApiValidationError(
            "VALIDATION_MISSING_AGENT_TYPE",
            "Agent type is required",
        )
    if str(agent_type).strip() not in ALLOWED_AGENT_TYPES:
        raise ApiValidationError(
            "VALIDATION_INVALID_AGENT_TYPE",
            "Unsupported agent type",
        )


def validation_error_detail(code: str, message: str) -> dict:
    return {"error_code": code, "message": message}
