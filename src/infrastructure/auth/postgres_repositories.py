from __future__ import annotations

"""PostgreSQL repository adapters for auth aggregates.

This module maps low-level row dictionaries into domain entities and keeps SQL
details localized to the infrastructure layer.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.domain.auth.entities import RefreshSession, User


class CursorLike(Protocol):
    """Minimal DB-API cursor surface required by these adapters."""

    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...


class ConnectionLike(Protocol):
    """Connection surface needed to open repository cursors."""

    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_user(row: dict[str, Any] | None) -> User | None:
    """Converts a raw users row to a domain User entity."""

    if row is None:
        return None
    return User(
        id=row["id"],
        email_normalized=row["email_normalized"],
        password_hash=row["password_hash"],
        email_verified=row["email_verified"],
        role=row["role"],
        auth_provider_id=row.get("auth_provider_id"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        deleted_at=row.get("deleted_at"),
    )


def _row_to_refresh_session(row: dict[str, Any] | None) -> RefreshSession | None:
    """Converts a raw refresh-session row to a domain RefreshSession entity."""

    if row is None:
        return None
    return RefreshSession(
        id=row["id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        token_jti=row["token_jti"],
        family_id=row["family_id"],
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        revoked_at=row.get("revoked_at"),
        replaced_by_session_id=row.get("replaced_by_session_id"),
        reuse_detected_at=row.get("reuse_detected_at"),
        user_agent=row.get("user_agent"),
        ip=row.get("ip"),
    )


class PostgresUserRepository:
    """User persistence adapter with explicit soft/hard delete semantics.

    `soft_delete` is idempotent (`deleted_at IS NULL` guard) and returns the
    mutated row only on the first delete.
    """

    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, user: User) -> User:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO users (
                    id, email_normalized, password_hash, email_verified,
                    role, auth_provider_id, created_at, updated_at, deleted_at
                ) VALUES (
                    %(id)s, %(email_normalized)s, %(password_hash)s, %(email_verified)s,
                    %(role)s, %(auth_provider_id)s, %(created_at)s, %(updated_at)s, %(deleted_at)s
                )
                RETURNING *
                """,
                asdict(user),
            )
            row = cur.fetchone()
        return _row_to_user(row) or user

    def get_by_email(self, email_normalized: str) -> User | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM users WHERE email_normalized = %(email_normalized)s",
                {"email_normalized": email_normalized},
            )
            return _row_to_user(cur.fetchone())

    def get_by_id(self, user_id: str) -> User | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM users WHERE id = %(id)s", {"id": user_id})
            return _row_to_user(cur.fetchone())

    def soft_delete(self, user_id: str, deleted_at: datetime) -> User | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE users
                SET deleted_at = %(deleted_at)s, updated_at = %(deleted_at)s
                WHERE id = %(id)s AND deleted_at IS NULL
                RETURNING *
                """,
                {"id": user_id, "deleted_at": deleted_at},
            )
            return _row_to_user(cur.fetchone())

    def hard_delete(self, user_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %(id)s", {"id": user_id})
            return cur.rowcount > 0


class PostgresRefreshSessionRepository:
    """Refresh-session adapter enforcing one-time rotation primitives.

    Methods expose low-level lifecycle operations; atomic composition is handled
    by the calling unit of work.
    """

    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, session: RefreshSession) -> RefreshSession:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO auth_refresh_sessions (
                    id, user_id, token_hash, token_jti, family_id,
                    issued_at, expires_at, revoked_at, replaced_by_session_id,
                    reuse_detected_at, user_agent, ip
                ) VALUES (
                    %(id)s, %(user_id)s, %(token_hash)s, %(token_jti)s, %(family_id)s,
                    %(issued_at)s, %(expires_at)s, %(revoked_at)s, %(replaced_by_session_id)s,
                    %(reuse_detected_at)s, %(user_agent)s, %(ip)s
                )
                RETURNING *
                """,
                asdict(session),
            )
            row = cur.fetchone()
        return _row_to_refresh_session(row) or session

    def get_active_by_token_hash(self, token_hash: str, now: datetime) -> RefreshSession | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM auth_refresh_sessions
                WHERE token_hash = %(token_hash)s
                  AND revoked_at IS NULL
                  AND expires_at > %(now)s
                """,
                {"token_hash": token_hash, "now": now},
            )
            return _row_to_refresh_session(cur.fetchone())

    def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM auth_refresh_sessions WHERE token_hash = %(token_hash)s",
                {"token_hash": token_hash},
            )
            return _row_to_refresh_session(cur.fetchone())

    def revoke(self, session_id: str, revoked_at: datetime) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_refresh_sessions
                SET revoked_at = %(revoked_at)s
                WHERE id = %(id)s AND revoked_at IS NULL
                """,
                {"id": session_id, "revoked_at": revoked_at},
            )

    def rotate(
        self,
        *,
        old_session_id: str,
        new_session: RefreshSession,
        revoked_at: datetime,
    ) -> RefreshSession | None:
        """Revokes old session then inserts replacement within one transaction.

        Returns:
            RefreshSession | None: Inserted replacement, or ``None`` when the
            old session was already revoked (reuse or concurrent rotation).
        """

        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE auth_refresh_sessions
                SET revoked_at = %(revoked_at)s, replaced_by_session_id = %(next_id)s
                WHERE id = %(id)s AND revoked_at IS NULL
                """,
                {"id": old_session_id, "revoked_at": revoked_at, "next_id": new_session.id},
            )
            if cur.rowcount != 1:
                return None
            cur.execute(
                """
                INSERT INTO auth_refresh_sessions (
                    id, user_id, token_hash, token_jti, family_id,
                    issued_at, expires_at, revoked_at, replaced_by_session_id,
                    reuse_detected_at, user_agent, ip
                ) VALUES (
                    %(id)s, %(user_id)s, %(token_hash)s, %(token_jti)s, %(family_id)s,
                    %(issued_at)s, %(expires_at)s, %(revoked_at)s, %(replaced_by_session_id)s,
                    %(reuse_detected_at)s, %(user_agent)s, %(ip)s
                )
                RETURNING *
                """,
                asdict(new_session),
            )
            row = cur.fetchone()
        return _row_to_refresh_session(row) or new_session

    def revoke_family(self, family_id: str, revoked_at: datetime) -> int:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_refresh_sessions
                SET revoked_at = %(revoked_at)s
                WHERE family_id = %(family_id)s AND revoked_at IS NULL
                """,
                {"family_id": family_id, "revoked_at": revoked_at},
            )
            return cur.rowcount

    def mark_reuse_detected(self, session_id: str, detected_at: datetime) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_refresh_sessions
                SET reuse_detected_at = %(detected_at)s
                WHERE id = %(id)s
                """,
                {"id": session_id, "detected_at": detected_at},
            )

    def revoke_all_by_user_id(self, user_id: str, revoked_at: datetime) -> int:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE auth_refresh_sessions
                SET revoked_at = %(revoked_at)s
                WHERE user_id = %(user_id)s AND revoked_at IS NULL
                """,
                {"user_id": user_id, "revoked_at": revoked_at},
            )
            return cur.rowcount
