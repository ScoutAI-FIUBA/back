# ScoutAI Auth Foundation — Spec

## Scope

### In Scope
- User base: `email`, `password_hash`, `email_verified=false`, `role='user'`, `auth_provider_id` nullable, timestamps.
- Endpoints: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`.
- Access token JWT (TTL 15m).
- Refresh token opaco con rotación (TTL 7d).
- Logout con invalidación de refresh.
- Contrato de errores uniforme.
- Arquitectura hexagonal DB-agnostic con Postgres como primer adapter.

### Out of Scope
- Verificación de email end-to-end.
- RBAC completo.
- Soft delete.
- MFA/SSO.

## Requirements (verificables)

### 1) User Registration
The system **MUST** allow user registration with unique email and password hash storage only.

#### Scenario: Register success
- **GIVEN** no existing user with the same normalized email
- **WHEN** client calls `POST /auth/register` with valid email/password
- **THEN** user is created with `email_verified=false`, `role='user'`, `auth_provider_id=null`
- **AND** `password_hash` is never returned

#### Scenario: Duplicate email
- **GIVEN** an existing user with same normalized email
- **WHEN** register is requested
- **THEN** API returns error envelope
- **AND** no second user is created

### 2) Login and Token Issuance
The system **MUST** authenticate credentials and issue:
- access JWT with TTL **15m**
- refresh opaque token with TTL **7d**

#### Scenario: Login success
- **GIVEN** active user with valid credentials
- **WHEN** `POST /auth/login`
- **THEN** API returns access JWT + refresh token
- **AND** JWT includes required claims

#### Scenario: Invalid credentials
- **GIVEN** wrong email or password
- **WHEN** `POST /auth/login`
- **THEN** API returns auth error envelope
- **AND** no session tokens are issued

### 3) Refresh Rotation
The system **MUST** rotate refresh token on each successful `POST /auth/refresh` and invalidate previous token.

#### Scenario: Refresh success
- **GIVEN** valid non-revoked refresh token
- **WHEN** `POST /auth/refresh`
- **THEN** new access + new refresh are issued
- **AND** previous refresh becomes unusable

#### Scenario: Refresh replay/reuse
- **GIVEN** an already-rotated or revoked refresh token
- **WHEN** token is presented again
- **THEN** request fails with auth error
- **AND** no new tokens are issued

### 4) Logout Invalidation
The system **MUST** invalidate refresh/session credentials on `POST /auth/logout`.

#### Scenario: Logout success
- **GIVEN** active refresh credential
- **WHEN** `POST /auth/logout`
- **THEN** credential is invalidated
- **AND** subsequent refresh fails

#### Scenario: Logout idempotency
- **GIVEN** already-invalidated credential
- **WHEN** `POST /auth/logout`
- **THEN** API responds safely without leaking state

### 5) Authenticated Identity (`/auth/me`)
The system **MUST** return authenticated user identity for valid access JWT.

#### Scenario: Me success
- **GIVEN** valid access JWT
- **WHEN** `GET /auth/me`
- **THEN** API returns minimal user identity
- **AND** excludes secret fields

#### Scenario: Invalid/missing token
- **GIVEN** missing, malformed or expired access JWT
- **WHEN** `GET /auth/me`
- **THEN** API returns auth error envelope

### 6) Unified Error Contract
All auth endpoints **MUST** return:

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

`details` is optional.

## Acceptance Criteria per Endpoint

### `POST /auth/register`
- Creates user with defaults (`email_verified=false`, `role='user'`, `auth_provider_id=null`).
- Rejects duplicate email.
- Never returns `password_hash`.

### `POST /auth/login`
- Validates credentials.
- Returns access JWT + refresh opaque.
- Applies TTLs: access 15m / refresh 7d.

### `POST /auth/refresh`
- Accepts valid refresh and rotates.
- Invalidates previous refresh.
- Rejects replay/reuse.

### `POST /auth/logout`
- Invalidates refresh/session.
- Prevents future refresh with same credential.

### `GET /auth/me`
- Requires valid access JWT.
- Returns authenticated identity without secrets.

## Security Invariants

1. Passwords are never stored in plaintext.
2. Access JWT lifetime is strictly 15m.
3. Refresh rotation is mandatory on successful refresh.
4. Refresh reuse is rejected.
5. JWT minimum claims required: `sub`, `iss`, `aud`, `iat`, `exp`, `jti`.
6. Error responses never expose secrets/internal stack details.

## Architecture Constraints (DB-agnostic)

1. Domain/Application MUST NOT import SQL drivers or Postgres libraries.
2. Use cases depend on ports, not concrete adapters.
3. SQL and Postgres details live only in infrastructure adapters.
4. Changing persistence adapter must not require domain/app contract changes.

## Token Claims

### Required
- `sub`, `iss`, `aud`, `iat`, `exp`, `jti`

### Recommended
- `role`, `email_verified`
