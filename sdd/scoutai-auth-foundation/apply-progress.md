# Apply Progress — scoutai-auth-foundation

## Batch
- Work unit: PR4 / Unit 4 (Postgres + wiring + docs)
- Delivery mode: chained PR slice (`feature-branch-chain`)
- Boundary: Postgres persistence adapters + final app wiring + API contract docs

## Completed Tasks (cumulative)
- [x] 1.1 Domain auth foundations: `User`, `RefreshSession`, `Email`, `PlainPassword`, `TokenPair`, `AuthIdentity`
- [x] 1.2 Application auth ports: repository/security/clock/id/uow contracts
- [x] 1.3 Base auth error taxonomy and neutral mapper
- [x] 2.1 Register/Login use cases with defaults and hash-only storage
- [x] 2.2 Security adapters: JWT access issuer, password hasher adapter, opaque refresh token service
- [x] 2.3 Auth HTTP router for `POST /auth/register` and `POST /auth/login` with uniform error envelope
- [x] 3.1 Refresh/logout/me use cases
- [x] 3.2 Refresh/logout/me endpoints
- [x] 4.1 Postgres repositories + migration
- [x] 4.2 Main wiring
- [x] 4.3 API docs update

## Remaining Tasks
- None.

## Files Changed (this batch)
- `src/infrastructure/auth/postgres_repositories.py` (new)
- `src/infrastructure/auth/postgres_user_repository.py` (new)
- `src/infrastructure/auth/postgres_refresh_session_repository.py` (new)
- `src/infrastructure/auth/jwt_access_token_resolver.py` (new)
- `src/infrastructure/auth/migrations/001_auth_foundation.sql` (new)
- `src/infrastructure/auth/__init__.py` (modified)
- `src/interfaces/http/main.py` (modified)
- `tests/infrastructure/auth/test_postgres_repositories.py` (new)
- `tests/infrastructure/auth/test_jwt_access_token_resolver.py` (new)
- `tests/interfaces/http/test_main_wiring.py` (new)
- `specs/api/auth.md` (new)
- `specs/api/README.md` (modified)
- `requirements.txt` (modified)
- `specs/prd/scoutai-auth-foundation-tasks.md` (updated checkboxes)

## Validation
- Executed: `.venv/bin/python -m unittest tests.infrastructure.auth.test_postgres_repositories tests.infrastructure.auth.test_jwt_access_token_resolver tests.interfaces.http.test_main_wiring`
- Result: PASS
- Executed: `.venv/bin/python -m unittest tests.domain.auth.test_value_objects tests.application.auth.test_ports_contract tests.application.auth.test_errors tests.application.auth.test_register_login_use_cases tests.application.auth.test_refresh_logout_me_use_cases tests.infrastructure.auth.test_security_adapters tests.infrastructure.auth.test_postgres_repositories tests.infrastructure.auth.test_jwt_access_token_resolver tests.interfaces.http.test_auth_register_login tests.interfaces.http.test_auth_session_endpoints tests.interfaces.http.test_main_wiring`
- Result: PASS

## Notes
- Strict TDD mode resolved as Standard (no cached `sdd/back/testing-capabilities` found).
- Domain/Application remain DB-agnostic (no SQL/Postgres imports in these layers).
- `/auth/me` now uses real JWT verification (signature + required claims + issuer/audience + exp) via infrastructure adapter.
