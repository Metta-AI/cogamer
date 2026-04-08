"""Softmax token authentication for the cogamer API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import httpx

SOFTMAX_VALIDATE_URL = "https://softmax.com/api/validate"

_token_cache: dict[str, AuthenticatedUser] = {}


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    name: str
    is_team_member: bool


@dataclass
class AuthenticatedCogamer:
    """Identity for a cogamer authenticating with its own token."""

    cogamer_name: str


# Union type for either caller kind
Caller = Union[AuthenticatedUser, AuthenticatedCogamer]


def validate_softmax_token(token: str) -> AuthenticatedUser | None:
    """Validate a softmax Bearer token. Returns user info or None."""
    if token in _token_cache:
        return _token_cache[token]

    try:
        resp = httpx.get(
            SOFTMAX_VALIDATE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        data = resp.json()
    except Exception:
        return None

    if not data.get("valid"):
        return None

    user_data = data["user"]
    user = AuthenticatedUser(
        id=user_data["id"],
        email=user_data["email"],
        name=user_data["name"],
        is_team_member=user_data.get("isSoftmaxTeamMember", False),
    )
    _token_cache[token] = user
    return user
