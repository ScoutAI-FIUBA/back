# HTTP Composition Refactor

Decision: `main.py` is now a thin composition root. Domain-neutral wiring logic moved to dedicated modules so endpoint behavior stays stable while composition becomes easier to extend and review.

## Responsibilities

- `src/interfaces/http/main.py`: composition root only (instantiate app, read env, compose dependencies, wire middleware/handlers/routes).
- `src/interfaces/http/bootstrap/`: framework bootstrap wiring and dependency composition.
- `src/interfaces/http/middleware/`: cross-cutting HTTP middleware (auth-by-default and whitelist behavior).
- `src/interfaces/http/routes/`: route factories and endpoint contracts.
- `src/interfaces/http/errors/`: HTTP error handler registration.

## File Map

- `src/interfaces/http/main.py`
- `src/interfaces/http/bootstrap/__init__.py`
- `src/interfaces/http/bootstrap/config.py`
- `src/interfaces/http/bootstrap/dependencies.py`
- `src/interfaces/http/bootstrap/router_wiring.py`
- `src/interfaces/http/bootstrap/health_routes.py`
- `src/interfaces/http/middleware/__init__.py`
- `src/interfaces/http/middleware/auth_middleware.py`
- `src/interfaces/http/routes/__init__.py`
- `src/interfaces/http/routes/auth_router.py`
- `src/interfaces/http/routes/team_router.py`
- `src/interfaces/http/routes/players_router.py`
- `src/interfaces/http/errors/__init__.py`
- `src/interfaces/http/errors/error_handlers.py`

## Extension Guidance

- Keep `main.py` thin and declarative: read env, compose dependencies, register hooks.
- Add env/config parsing in `bootstrap/config.py`.
- Add dependency/container wiring in `bootstrap/dependencies.py`.
- Add router inclusion orchestration in `bootstrap/router_wiring.py` and keep endpoint code in `routes/`.
- Add middleware in `middleware/` and keep auth whitelist rules centralized there.
- Add request/response exception mapping in `errors/`.
