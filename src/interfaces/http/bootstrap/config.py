from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

AuthCookieSameSite = Literal["strict", "lax", "none"]

DEFAULT_DB_HEALTH_CONNECT_TIMEOUT_SECONDS = 5


def require_env(name: str) -> str:
    """Reads a required environment variable and fails fast when missing/blank."""

    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def db_health_connect_timeout_seconds() -> int:
    """Returns DB health-check timeout with safe fallback parsing.

    Invalid or blank values fall back to the default. Non-positive explicit values
    are rejected to avoid silently accepting broken production configuration.
    """

    raw = os.getenv("DB_HEALTH_CONNECT_TIMEOUT_SECONDS")
    if raw is None or raw.strip() == "":
        return DEFAULT_DB_HEALTH_CONNECT_TIMEOUT_SECONDS
    try:
        value = int(raw.strip())
    except ValueError:
        return DEFAULT_DB_HEALTH_CONNECT_TIMEOUT_SECONDS
    if value <= 0:
        raise RuntimeError("DB_HEALTH_CONNECT_TIMEOUT_SECONDS must be a positive integer")
    return value


def auth_refresh_cookie_samesite() -> AuthCookieSameSite:
    """Returns SameSite for the refresh cookie.

    Local dev uses ``strict`` (front and back share localhost). Production deploys
    front and back on different origins, so refresh needs ``none`` + ``Secure``.
    """

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    raw = os.getenv("AUTH_COOKIE_SAMESITE", "").strip().lower()
    if raw == "":
        return "none" if app_env != "development" else "strict"
    if raw not in ("strict", "lax", "none"):
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be one of: strict, lax, none")
    return raw  # type: ignore[return-value]


def parse_cors_origins() -> list[str]:
    """Parses ``CORS_ORIGINS`` with explicit wildcard safety rules.

    ``*`` is accepted only as a standalone value so production config cannot
    accidentally combine unrestricted and restricted origins.
    """

    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw == "":
        return []
    if raw == "*":
        return ["*"]

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        if len(origins) > 1:
            raise RuntimeError("CORS_ORIGINS cannot mix '*' with explicit origins")
        return ["*"]
    return origins


def configure_cors(app: FastAPI) -> None:
    """Applies CORS policy based on ``APP_ENV`` and ``CORS_ORIGINS``.

    Development is intentionally permissive for localhost origins only. Non-dev
    environments must provide explicit origins or opt into a standalone wildcard.
    """

    app_env = os.getenv("APP_ENV", "development").strip().lower()

    if app_env == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return

    cors_origins = parse_cors_origins()
    if not cors_origins:
        raise RuntimeError(
            "Missing required environment variable: CORS_ORIGINS "
            "(required when APP_ENV is not development)"
        )

    if cors_origins == ["*"]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
