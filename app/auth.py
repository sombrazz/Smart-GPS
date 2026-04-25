from __future__ import annotations

import secrets
from typing import Any


DEMO_USERS: dict[str, dict[str, Any]] = {
    "condutor@demo.com": {
        "id": "user-driver-01",
        "email": "condutor@demo.com",
        "password": "demo123",
        "name": "Condutor Demo",
        "role": "driver",
        "vehicle_id": "V-01",
    },
    "supervisor@demo.com": {
        "id": "user-supervisor-01",
        "email": "supervisor@demo.com",
        "password": "demo123",
        "name": "Supervisor Demo",
        "role": "supervisor",
        "vehicle_id": None,
    },
}

ACTIVE_TOKENS: dict[str, str] = {}


def authenticate_user(identifier: str, password: str) -> dict[str, Any] | None:
    user = DEMO_USERS.get(identifier.lower())
    if not user or user["password"] != password:
        return None
    return sanitize_user(user)


def create_session(email: str) -> str:
    token = secrets.token_urlsafe(24)
    ACTIVE_TOKENS[token] = email.lower()
    return token


def get_user_by_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    email = ACTIVE_TOKENS.get(token)
    if not email:
        return None
    user = DEMO_USERS.get(email)
    if not user:
        return None
    return sanitize_user(user)


def revoke_session(token: str | None) -> None:
    if token:
        ACTIVE_TOKENS.pop(token, None)


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "vehicle_id": user["vehicle_id"],
    }
