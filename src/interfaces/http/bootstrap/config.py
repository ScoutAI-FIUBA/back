from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DEFAULT_DB_HEALTH_CONNECT_TIMEOUT_SECONDS = 5


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def db_health_connect_timeout_seconds() -> int:
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


def parse_cors_origins() -> list[str]:
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
