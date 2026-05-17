# Tasks: ScoutAI Auth Foundation

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 520-760 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR1 Foundation → PR2 Register/Login → PR3 Refresh/Logout/Me → PR4 Postgres+Wiring |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Domain+ports base (SCOUTAI-29) | PR1 | base=feature/tracker; includes unit tests |
| 2 | Register/Login + JWT access (SCOUTAI-30) | PR2 | base=PR1 branch; add contract tests |
| 3 | Refresh rotation + logout + me (SCOUTAI-31) | PR3 | base=PR2 branch; include replay/reuse tests |
| 4 | Postgres adapters + app wiring + docs | PR4 | base=PR3 branch; integration tests |

## Phase 1: Foundation (SCOUTAI-29)

- [x] 1.1 Crear `src/domain/auth/entities.py` y `src/domain/auth/value_objects.py` con `User`, `RefreshSession`, `Email`, `PlainPassword`, `TokenPair`, `AuthIdentity`.
  - Prueba: `tests/domain/auth/test_value_objects.py` (normalización email, policy password, expiración/revocación).
- [x] 1.2 Crear `src/application/auth/ports.py` con `UserRepositoryPort`, `RefreshSessionRepositoryPort`, `PasswordHasherPort`, `TokenIssuerPort`, `RefreshTokenServicePort`, `ClockPort`, `IdGeneratorPort`, `UnitOfWorkPort`.
  - Prueba: `tests/application/auth/test_ports_contract.py` (firma mínima y dependencias sin SQL).
- [x] 1.3 Crear `src/application/auth/errors.py` con taxonomía `AUTH_*` y mapper neutro.
  - Prueba: `tests/application/auth/test_errors.py` (codes estables + details opcional).

## Phase 2: Register/Login (SCOUTAI-30)

- [x] 2.1 Implementar `src/application/auth/use_cases.py` (`RegisterUserUseCase`, `LoginUseCase`) con defaults y hash-only storage.
  - Prueba: `tests/application/auth/test_register_login_use_cases.py` (registro OK/duplicado, credenciales inválidas, no plaintext).
- [x] 2.2 Crear `src/infrastructure/auth/jwt_token_issuer.py`, `argon2_password_hasher.py`, `opaque_refresh_token_service.py` (TTL 15m/7d, claims requeridos).
  - Prueba: `tests/infrastructure/auth/test_security_adapters.py` (claims mínimos, verify hash, TTL).
- [x] 2.3 Crear `src/interfaces/http/auth_router.py` para `POST /auth/register` y `POST /auth/login`, envelope de error uniforme.
  - Prueba: `tests/interfaces/http/test_auth_register_login.py` (status, shape, no `password_hash`).

## Phase 3: Refresh/Logout/Me (SCOUTAI-31)

- [x] 3.1 Extender `use_cases.py` con `RefreshSessionUseCase`, `LogoutUseCase`, `GetCurrentUserUseCase` (rotación estricta + reuse detection + revoke family).
  - Prueba: `tests/application/auth/test_refresh_logout_me_use_cases.py` (rotate success, replay rejected, logout idempotente, me token inválido).
- [x] 3.2 Extender `auth_router.py` con `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`; refresh token por cookie `HttpOnly+Secure+SameSite`.
  - Prueba: `tests/interfaces/http/test_auth_session_endpoints.py` (Set-Cookie flags, refresh via cookie, unauthorized paths).

## Phase 4: Postgres + Wiring + Verification

- [x] 4.1 Crear `src/infrastructure/auth/postgres_user_repository.py` y `postgres_refresh_session_repository.py` + migración inicial `users` y `auth_refresh_sessions`.
  - Prueba: `tests/infrastructure/auth/test_postgres_repositories.py` (unique email/token_hash, rotate atómico, revoke family).
- [x] 4.2 Modificar `src/interfaces/http/main.py` para registrar auth router y dependencias por puertos; mantener `/health`.
  - Prueba: `tests/interfaces/http/test_main_wiring.py` (app levanta + rutas auth presentes).
- [x] 4.3 Actualizar `specs/api/README.md` o nuevo `specs/api/auth.md` con contrato final (cookies + errores + claims).
  - Prueba: checklist manual de consistencia contra spec (`register/login/refresh/logout/me`).
