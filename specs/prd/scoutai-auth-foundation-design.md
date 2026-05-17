# ScoutAI Auth Foundation — Technical Design

## Technical Approach
Implementar auth como módulo hexagonal nuevo (`domain/auth`, `application/auth`, `infrastructure/auth`, `interfaces/http/auth_router.py`) manteniendo el patrón actual (ports + use case + adapter) y evitando acoplar dominio/aplicación a Postgres o FastAPI. Postgres será el primer adapter de persistencia; JWT/clock/hash serán puertos para testabilidad y portabilidad.

## Architecture Decisions

| Decision | Options | Chosen | Why / Tradeoff |
|---|---|---|---|
| Session model | Stateless-only JWT vs refresh persisted | Access JWT + persisted opaque refresh | Cumple rotación/reuse detection. Más complejidad operativa, pero seguridad superior. |
| Refresh storage | Store raw token vs store hash | Store `refresh_token_hash` | Reduce impacto si hay leak DB; requiere hash/compare adicional. |
| Rotation policy | Soft rotate (old usable briefly) vs strict single-use | Strict rotation + family tracking | Cumple spec de replay rejection; puede aumentar falsos negativos en concurrencia extrema. |
| Logout semantics | Revoke current only vs family-wide | Current session revoke now; family-wide on detected reuse | Balancea UX y seguridad; reuse activa contención. |
| Error strategy | HTTP-native ad hoc vs domain error taxonomy | Domain/App error codes mapped to HTTP | Contrato uniforme `{error:{...}}`, desacople de transporte. |

## Domain Model (Entities / VOs)
- `User` (Entity): `id, email_normalized, password_hash, email_verified, role, auth_provider_id, created_at, updated_at`.
- `RefreshSession` (Entity): `id, user_id, token_hash, token_jti, family_id, issued_at, expires_at, revoked_at, replaced_by_session_id, reuse_detected_at, user_agent, ip`.
- `Email` (VO): normalización + validación sintáctica.
- `PlainPassword` (VO): validaciones mínimas de política.
- `PasswordHash` (VO): representa hash opaco.
- `TokenPair` (VO): `access_token, refresh_token, token_type, expires_in`.
- `AuthIdentity` (VO): `user_id, email, role, email_verified`.

## Ports and Use Cases

### Application Ports
- `UserRepositoryPort`: `create`, `get_by_email`, `get_by_id`.
- `RefreshSessionRepositoryPort`: `create`, `get_active_by_token_hash`, `revoke`, `rotate`, `revoke_family`.
- `PasswordHasherPort`: `hash`, `verify`.
- `TokenIssuerPort`: `issue_access(identity, jti, exp)`.
- `RefreshTokenServicePort`: `generate_plain`, `hash`, `fingerprint`.
- `ClockPort`, `IdGeneratorPort`, `UnitOfWorkPort`.

### Use Cases
- `RegisterUserUseCase`
- `LoginUseCase`
- `RefreshSessionUseCase`
- `LogoutUseCase`
- `GetCurrentUserUseCase`

## Adapters
- **Infra/Postgres**: repos concretos (`postgres_user_repository.py`, `postgres_refresh_session_repository.py`) con SQL aislado.
- **Infra/Security**: `jwt_token_issuer.py`, `argon2_password_hasher.py`, `opaque_refresh_token_service.py`.
- **Interface/HTTP FastAPI**: `auth_router.py` para `/auth/register|login|refresh|logout|me`, mapping request/response y error envelope.

## Persistence Conceptual Schema (DB-agnostic, Postgres first)
- `users`
  - PK `id`
  - UNIQUE `email_normalized`
  - `password_hash`, `email_verified` default false, `role` default 'user', `auth_provider_id` nullable, timestamps.
- `auth_refresh_sessions`
  - PK `id`, FK `user_id -> users.id`
  - UNIQUE `token_hash`
  - INDEX (`user_id`, `expires_at`), INDEX (`family_id`), INDEX partial active (`revoked_at IS NULL`)
  - `token_jti`, `family_id`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by_session_id`, `reuse_detected_at`, metadata (`ip`, `user_agent`).

## Token and Session Policies
- Access JWT TTL fijo 15m; claims obligatorios: `sub, iss, aud, iat, exp, jti`; recomendados: `role, email_verified`.
- Refresh opaque TTL 7d, guardado hasheado.
- Refresh exitoso: transacción atómica `invalidate old + create new`.
- Reuse detection: si token inválido por rotado/revocado pero existe huella conocida, marcar `reuse_detected_at`, revocar `family_id`, devolver `AUTH_REFRESH_REUSED`.
- Logout: revoca sesión actual (idempotente, sin filtrar existencia).

## Error Strategy
Taxonomía de app:
- `AUTH_INVALID_CREDENTIALS`, `AUTH_TOKEN_EXPIRED`, `AUTH_TOKEN_INVALID`, `AUTH_REFRESH_REUSED`, `AUTH_UNAUTHORIZED`, `AUTH_EMAIL_ALREADY_EXISTS`, `AUTH_VALIDATION_ERROR`, `AUTH_INTERNAL`.

HTTP mapping:
- 400: validation
- 401: invalid credentials/token/unauthorized
- 409: duplicate email
- 500: internal

Siempre responder:
`{ "error": { "code": "...", "message": "...", "details": {...?} } }`

## Textual Flow Diagram
```
REGISTER: HTTP -> RegisterUC -> UserRepo(create) -> response(user public)
LOGIN:    HTTP -> LoginUC -> UserRepo(by email) -> PasswordHasher(verify)
         -> TokenIssuer(issue access) + RefreshRepo(create hashed refresh) -> TokenPair
REFRESH:  HTTP -> RefreshUC -> RefreshRepo(find active by hash)
         -> [valid] rotate(old revoke + new create) -> new TokenPair
         -> [reused/invalid] revoke family (if applicable) -> auth error
LOGOUT:   HTTP -> LogoutUC -> RefreshRepo(revoke current) -> 204/200 idempotent
ME:       HTTP(auth middleware parse JWT) -> GetCurrentUserUC -> UserRepo(by id) -> identity
```

## Minimal Test Plan by Layer
| Layer | Minimum tests |
|---|---|
| Domain | Email normalization/validation; password policy VO; refresh expiry/revoked/reuse rules. |
| Application (unit) | Register duplicate/non-duplicate; login valid/invalid; refresh rotate success; refresh replay rejected; logout idempotent; me with missing user/token invalid. |
| Infrastructure (integration) | Postgres repo constraints (unique email, token hash unique), transactional rotation atomicity, family revoke query correctness. |
| Interface HTTP (contract) | Endpoint status codes + envelope shape + no `password_hash` leakage; JWT required on `/auth/me`. |

## File Changes (planned)
| File | Action | Description |
|---|---|---|
| `src/domain/auth/*.py` | Create | Entities/VOs and domain rules. |
| `src/application/auth/ports.py` | Create | Auth-specific port contracts. |
| `src/application/auth/use_cases.py` | Create | Register/login/refresh/logout/me use cases. |
| `src/infrastructure/auth/*.py` | Create | Postgres + JWT/hash/refresh adapters. |
| `src/interfaces/http/auth_router.py` | Create | FastAPI routes and DTO mapping. |
| `src/interfaces/http/main.py` | Modify | Wire auth router and dependencies. |
| `specs/prd/scoutai-auth-foundation-design.md` | Create | This design artifact. |

## Migration / Rollout
No migration compleja: crear tablas `users` y `auth_refresh_sessions` en primer deploy del módulo auth. Entrega en feature-branch-chain como ya definido.

## Open Questions
- Definir si refresh via cookie HttpOnly o body JSON en esta fase (impacta cliente y CSRF).
- Definir nivel de hashing/cost final (Argon2id params) según presupuesto de latencia.
