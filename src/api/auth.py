"""Authentication helpers for API middleware."""

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set


@dataclass
class AuthPrincipal:
    subject: str
    audience: str
    scopes: Set[str]
    workspace_role: str
    token_id: Optional[str]


class AuthError(ValueError):
    def __init__(
        self,
        message: str,
        status_code: int = 401,
        reason: str = "invalid",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class AuthPolicy:
    def __init__(
        self,
        audience: str = "agent-workers",
        required_scope: str = "agent:worker",
        signing_secret: str = "",
        issuer: str = "",
        allowed_roles: Optional[Iterable[str]] = None,
        revoked_token_ids: Optional[Iterable[str]] = None,
    ):
        self.audience = audience
        self.required_scope = required_scope
        self.signing_secret = signing_secret
        self.issuer = issuer
        self.allowed_roles = set(
            allowed_roles or {"admin", "operator", "worker"}
        )
        self.revoked_token_ids = set(revoked_token_ids or set())

    def authenticate(
        self,
        token: str,
        now: Optional[float] = None,
    ) -> AuthPrincipal:
        claims = self._decode_claims(token)
        now = time.time() if now is None else now

        subject = self._string_claim(claims, "sub")
        if not subject:
            raise AuthError("Token subject is required", reason="missing_sub")

        token_id = self._optional_string_claim(claims, "jti")
        if token_id and token_id in self.revoked_token_ids:
            raise AuthError("Token has been revoked", reason="revoked")

        expires_at = self._numeric_claim(claims, "exp")
        if expires_at is None or expires_at <= now:
            raise AuthError("Token has expired", reason="expired")

        not_before = self._numeric_claim(claims, "nbf")
        if not_before is not None and not_before > now:
            raise AuthError("Token is not active yet", reason="not_active")

        if not self._audience_matches(claims.get("aud")):
            raise AuthError(
                "Token audience is not permitted",
                status_code=403,
                reason="wrong_audience",
            )

        issuer = self._optional_string_claim(claims, "iss")
        if self.issuer and issuer != self.issuer:
            raise AuthError(
                "Token issuer is not permitted",
                status_code=403,
                reason="wrong_issuer",
            )

        scopes = self._extract_scopes(claims)
        if self.required_scope not in scopes:
            raise AuthError(
                "Token scope is insufficient",
                status_code=403,
                reason="insufficient_scope",
            )

        role = (
            self._optional_string_claim(claims, "workspace_role")
            or self._optional_string_claim(claims, "role")
            or ""
        )
        if role not in self.allowed_roles:
            raise AuthError(
                "Workspace role is insufficient",
                status_code=403,
                reason="insufficient_role",
            )

        return AuthPrincipal(
            subject=subject,
            audience=self.audience,
            scopes=scopes,
            workspace_role=role,
            token_id=token_id,
        )

    def _decode_claims(self, token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthError("Bearer token must be a JWT", reason="malformed")
        header = self._decode_json_part(parts[0], "header")
        if header.get("alg") != "HS256":
            raise AuthError(
                "Bearer token algorithm is not permitted",
                reason="bad_algorithm",
            )
        if not self.signing_secret:
            raise AuthError(
                "JWT signing secret is not configured",
                reason="misconfigured",
            )
        self._verify_signature(token, parts[2])
        return self._decode_json_part(parts[1], "payload")

    def _decode_json_part(self, value: str, label: str) -> Dict[str, Any]:
        try:
            decoded = self._base64url_decode(value)
            data = json.loads(decoded.decode("utf-8"))
        except (
            binascii.Error,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            raise AuthError(
                f"Bearer token {label} is invalid",
                reason=f"invalid_{label}",
            ) from exc
        if not isinstance(data, dict):
            raise AuthError(
                f"Bearer token {label} must be an object",
                reason=f"invalid_{label}",
            )
        return data

    def _verify_signature(self, token: str, signature: str) -> None:
        signed_part = token.rsplit(".", 1)[0].encode("ascii")
        digest = hmac.new(
            self.signing_secret.encode("utf-8"),
            signed_part,
            hashlib.sha256,
        ).digest()
        expected = self._base64url_encode(digest)
        if not hmac.compare_digest(signature, expected):
            raise AuthError(
                "Bearer token signature is invalid",
                reason="bad_signature",
            )

    @staticmethod
    def _base64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))

    @staticmethod
    def _base64url_encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _string_claim(claims: Dict[str, Any], name: str) -> str:
        value = claims.get(name)
        return value if isinstance(value, str) and value.strip() else ""

    @staticmethod
    def _optional_string_claim(
        claims: Dict[str, Any],
        name: str,
    ) -> Optional[str]:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value
        return None

    @staticmethod
    def _numeric_claim(claims: Dict[str, Any], name: str) -> Optional[float]:
        value = claims.get(name)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _audience_matches(self, value: Any) -> bool:
        if isinstance(value, str):
            return value == self.audience
        if isinstance(value, list):
            return self.audience in value
        return False

    @staticmethod
    def _extract_scopes(claims: Dict[str, Any]) -> Set[str]:
        scopes: Set[str] = set()
        scope = claims.get("scope")
        if isinstance(scope, str):
            scopes.update(part for part in scope.split() if part)
        scp = claims.get("scp")
        if isinstance(scp, list):
            scopes.update(part for part in scp if isinstance(part, str))
        return scopes
