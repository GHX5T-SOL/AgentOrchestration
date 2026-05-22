"""Authentication and authorization helpers for protected API routes."""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Set, Tuple


ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}
READ_METHODS = {"GET", "HEAD"}
PUBLIC_API_PATHS = {"/api/v2/auth/token"}


class AuthError(Exception):
    """Base auth error carrying the HTTP status that should be returned."""

    status_code = 401


class AuthenticationError(AuthError):
    status_code = 401


class AuthorizationError(AuthError):
    status_code = 403


@dataclass(frozen=True)
class Principal:
    """Authenticated API principal and current workspace membership state."""

    subject: str
    workspace_id: str
    role: str
    scopes: Set[str] = field(default_factory=set)
    active: bool = True
    revoked: bool = False
    token_version: int = 1
    membership_version: int = 1
    expires_at: Optional[float] = None

    @classmethod
    def from_mapping(cls, data: Mapping) -> "Principal":
        scopes = data.get("scopes", [])
        if isinstance(scopes, str):
            scopes = [
                scope.strip()
                for scope in scopes.split(",")
                if scope.strip()
            ]
        return cls(
            subject=str(data["subject"]),
            workspace_id=str(data["workspace_id"]),
            role=str(data.get("role", "viewer")),
            scopes=set(scopes),
            active=bool(data.get("active", True)),
            revoked=bool(data.get("revoked", False)),
            token_version=int(data.get("token_version", 1)),
            membership_version=int(data.get("membership_version", 1)),
            expires_at=data.get("expires_at"),
        )


@dataclass(frozen=True)
class RoutePolicy:
    """Minimum permission needed before a protected handler can run."""

    scope: str
    min_role: str


class TokenAuthProvider:
    """Opaque bearer-token validator backed by a token registry.

    The provider keeps token parsing outside route handlers so redirects and
    endpoint code cannot execute until the principal is known to be current,
    active, and authorized for the protected route.
    """

    def __init__(
        self,
        tokens: Optional[Mapping[str, Principal]] = None,
        revoked_tokens: Optional[Iterable[str]] = None,
        current_memberships: Optional[Mapping[Tuple[str, str], int]] = None,
    ):
        self._tokens = dict(tokens or {})
        self._revoked_tokens = set(revoked_tokens or set())
        self._current_memberships = dict(current_memberships or {})

    @classmethod
    def from_env(cls) -> "TokenAuthProvider":
        token_payload = os.getenv("AO_AUTH_TOKENS", "{}")
        membership_payload = os.getenv("AO_AUTH_MEMBERSHIP_VERSIONS", "{}")
        raw_tokens = json.loads(token_payload)
        raw_memberships = json.loads(membership_payload)

        tokens = {
            token: Principal.from_mapping(principal)
            for token, principal in raw_tokens.items()
        }
        memberships = {
            tuple(key.split(":", 1)): int(version)
            for key, version in raw_memberships.items()
        }
        return cls(tokens=tokens, current_memberships=memberships)

    def authenticate(self, token: str) -> Principal:
        if token in self._revoked_tokens:
            raise AuthenticationError("Token has been revoked")

        principal = self._tokens.get(token)
        if principal is None:
            raise AuthenticationError("Invalid bearer token")

        if principal.revoked or not principal.active:
            raise AuthenticationError("Principal is not active")

        if (
            principal.expires_at is not None
            and principal.expires_at <= time.time()
        ):
            raise AuthenticationError("Bearer token has expired")

        key = (principal.subject, principal.workspace_id)
        current_version = self._current_memberships.get(
            key, principal.membership_version
        )
        if current_version != principal.membership_version:
            raise AuthenticationError("Principal membership is stale")

        return principal


def canonicalize_api_path(path: str) -> str:
    """Normalize trailing slashes before auth policy decisions."""

    normalized = "/" + path.lstrip("/")
    while len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def is_api_v2_path(path: str) -> bool:
    return path == "/api/v2" or path.startswith("/api/v2/")


def is_agent_path(path: str) -> bool:
    return path == "/api/v2/agents" or path.startswith("/api/v2/agents/")


def route_policy(method: str, path: str) -> Optional[RoutePolicy]:
    canonical_path = canonicalize_api_path(path)
    method = method.upper()

    if method == "OPTIONS":
        return None
    if canonical_path in PUBLIC_API_PATHS:
        return None
    if not is_api_v2_path(canonical_path):
        return None

    if is_agent_path(canonical_path):
        if method in READ_METHODS:
            return RoutePolicy(scope="agents:read", min_role="viewer")
        return RoutePolicy(scope="agents:write", min_role="operator")

    return RoutePolicy(scope="api:access", min_role="viewer")


def authorize(principal: Principal, policy: RoutePolicy) -> None:
    scopes = principal.scopes
    if "*" not in scopes and policy.scope not in scopes:
        raise AuthorizationError("Principal is missing the required scope")

    principal_rank = ROLE_RANK.get(principal.role, 0)
    required_rank = ROLE_RANK[policy.min_role]
    if principal_rank < required_rank:
        raise AuthorizationError("Principal role is insufficient")
