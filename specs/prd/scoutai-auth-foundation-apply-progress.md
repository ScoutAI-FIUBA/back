# Apply Progress — scoutai-auth-foundation

## Batch
- Work unit: Hotfix slice — logout delete-cookie propagation
- Delivery mode: chained PR slice (`feature-branch-chain`)
- Boundary: `POST /auth/logout` HTTP response contract + targeted test coverage

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
- [x] Hotfix: `POST /auth/logout` preserves `Set-Cookie` delete header in final response
- [x] Hotfix: contract test asserts logout delete-cookie header flags/value

## Remaining Tasks
- None.

## Files Changed (this batch)
- `src/interfaces/http/auth_router.py` (modified)
- `tests/interfaces/http/test_auth_session_endpoints.py` (modified)
- `specs/prd/scoutai-auth-foundation-apply-progress.md` (new)

## Validation
- Executed: `.venv/bin/python -m unittest tests.interfaces.http.test_auth_session_endpoints tests.interfaces.http.test_auth_register_login`
- Result: PASS

## Notes
- Root cause fixed: logout used injected `Response` to call `delete_cookie` but returned a new `Response`, dropping headers.
- Fix keeps same `Response` instance, sets status to `204`, and returns it.
- Strict TDD mode resolved as Standard (no cached `sdd/back/testing-capabilities` found).
