CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email_normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    role TEXT NOT NULL DEFAULT 'user',
    auth_provider_id TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS auth_refresh_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_jti TEXT NOT NULL,
    family_id TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    replaced_by_session_id TEXT NULL,
    reuse_detected_at TIMESTAMPTZ NULL,
    user_agent TEXT NULL,
    ip TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_sessions_user_expires
    ON auth_refresh_sessions (user_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_sessions_family
    ON auth_refresh_sessions (family_id);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_sessions_active
    ON auth_refresh_sessions (token_hash)
    WHERE revoked_at IS NULL;
