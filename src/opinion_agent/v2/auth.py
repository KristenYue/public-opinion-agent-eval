"""Small, explicit authentication boundary for the public V2 API.

The application deliberately does not invent a browser login or an identity
provider.  A deployment supplies short-lived/rotated API tokens through its
secret manager, and this module turns a verified token into a trusted subject.
Project membership is then checked by :mod:`opinion_agent.v2.jobs`.
"""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuthConfigurationError(RuntimeError):
    """The V2 service was enabled without a safe identity configuration."""


class AuthenticationError(PermissionError):
    """A caller did not present a configured API token."""


class Principal(BaseModel):
    """Trusted server-side identity derived from an API token, never request JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=200)


class StaticTokenAuthenticator:
    """Authenticate opaque API tokens from an environment-provided JSON map.

    ``V2_AUTH_TOKENS_JSON`` has the shape ``{"opaque-token": "subject"}``.
    Tokens are deployment secrets, are compared in constant time, and are never
    written to logs, responses, PostgreSQL, or the generated OpenAPI schema.
    This small adapter can be replaced at the application edge by an OIDC/API
    gateway integration without changing Project RBAC semantics.
    """

    def __init__(self, token_subjects: dict[str, str]) -> None:
        if not token_subjects:
            raise AuthConfigurationError("at least one V2 API token is required")
        validated: dict[str, str] = {}
        for token, subject in token_subjects.items():
            if not isinstance(token, str) or not token.strip():
                raise AuthConfigurationError("V2 API token values must be nonblank strings")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 200:
                raise AuthConfigurationError(
                    "V2 API token subjects must be nonblank strings up to 200 characters"
                )
            validated[token] = subject.strip()
        self._token_subjects = validated

    @classmethod
    def from_env(cls) -> "StaticTokenAuthenticator":
        raw = os.getenv("V2_AUTH_TOKENS_JSON", "").strip()
        if not raw:
            raise AuthConfigurationError(
                "V2_AUTH_TOKENS_JSON is required when the durable V2 API is enabled"
            )
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthConfigurationError("V2_AUTH_TOKENS_JSON must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise AuthConfigurationError("V2_AUTH_TOKENS_JSON must be a JSON object")
        return cls(parsed)

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise AuthenticationError("X-API-Key is required")
        for configured_token, subject in self._token_subjects.items():
            if hmac.compare_digest(token, configured_token):
                return Principal(subject=subject)
        raise AuthenticationError("invalid API token")
