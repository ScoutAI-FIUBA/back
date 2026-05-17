# Auth API Contract

## Base
- Prefix: `/auth`
- Error envelope:

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

`details` is optional.

## Endpoints

### POST /auth/register
- Body: `{ "email": "user@example.com", "password": "min-8-chars" }`
- 200 response:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "email_verified": false
  }
}
```

### POST /auth/login
- Body: `{ "email": "user@example.com", "password": "..." }`
- 200 response:

```json
{
  "access_token": "jwt",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "email_verified": false
  }
}
```

- Sets cookie `refresh_token` with:
  - `HttpOnly`
  - `Secure`
  - `SameSite=Strict`
  - `Path=/auth`
  - `Max-Age=604800`

### POST /auth/refresh
- Reads `refresh_token` cookie.
- 200 response: same payload shape as `/auth/login`.
- Rotates refresh token and sets a new `refresh_token` cookie with same flags.

### POST /auth/logout
- Reads `refresh_token` cookie if present.
- Revokes current session (idempotent).
- 204 response and deletes cookie `refresh_token` (`Path=/auth`, `HttpOnly`, `Secure`, `SameSite=Strict`).

### GET /auth/me
- Requires `Authorization: Bearer <access-token>`.
- 200 response:

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "email_verified": false
  }
}
```

### DELETE /auth/me
- Requires `Authorization: Bearer <access-token>`.
- Performs soft delete for the authenticated user.
- Side effects:
  - sets `users.deleted_at`
  - updates `users.updated_at`
  - revokes all active refresh sessions for that user
- Response: `204 No Content`.

## Internal/Admin Operations (no public endpoint)

### Hard delete user
- Implemented as an internal application operation (not exposed in `/auth` router).
- Behavior:
  - revoke all active refresh sessions for target user
  - physically delete user record

## JWT Access Token
- Required claims: `sub`, `iss`, `aud`, `iat`, `exp`, `jti`
- Additional claims: `role`, `email_verified`
- TTL: 15 minutes

## Refresh Token
- Opaque token persisted by hash.
- TTL: 7 days
- Rotation is strict single-use.
