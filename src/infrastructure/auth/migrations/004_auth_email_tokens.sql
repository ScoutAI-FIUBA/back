-- Single-use tokens delivered by email, for password reset and email
-- verification. Only the hash is stored, like auth_refresh_sessions, so a
-- leaked dump cannot be replayed against the account. Idempotent.

CREATE TABLE IF NOT EXISTS auth_email_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('password_reset', 'email_verification')),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL
);

-- Serves the per-user throttle, which counts recent requests of one purpose.
CREATE INDEX IF NOT EXISTS idx_auth_email_tokens_user_purpose
    ON auth_email_tokens (user_id, purpose, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auth_email_tokens_unused
    ON auth_email_tokens (token_hash)
    WHERE used_at IS NULL;
