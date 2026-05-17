# ScoutAI Auth Foundation — Proposal (PRD técnico)

## Objetivo
Unificar SCOUTAI-29, SCOUTAI-30 y SCOUTAI-31 en un cambio consistente para establecer la base de autenticación:
- entidad Usuario mínima,
- endpoint de login,
- manejo de sesión/token seguro y evolutivo.

## Decisiones cerradas

1. `email_verified` se incluye ahora con default `false`.
2. `deleted_at` (soft delete) se incluye en esta fase para desactivar cuentas y bloquear login/refresh.
3. `role` simple con default `user` (sin RBAC completo todavía).
4. `auth_provider_id` nullable reservado para futura federación.
5. Base de datos inicial: PostgreSQL.
6. Diseño DB-agnostic: dominio/aplicación desacoplados de motor y driver.
7. Tokens:
   - access JWT corto,
   - refresh opaco con rotación,
   - logout invalida refresh.
8. TTLs acordados:
   - access: 15 minutos,
   - refresh: 7 días.

## Alcance (In Scope)

- Modelo de usuario base para login local.
- Endpoints:
  - `POST /auth/register`
  - `POST /auth/login`
  - `POST /auth/refresh`
  - `POST /auth/logout`
  - `GET /auth/me`
- Validación de credenciales y emisión de tokens.
- Contrato uniforme de errores.
- Límites de arquitectura hexagonal y puertos/adapters.

## Fuera de alcance (Out of Scope)

- Verificación de email completa (flujo de envío/confirmación).
- RBAC granular.
- MFA/SSO.

## Contratos de alto nivel

### Login
Entrada: `email`, `password`.

Salida exitosa:
- `access_token`
- `token_type` (`Bearer`)
- `expires_in`
- `refresh_token`
- `user` mínimo (`id`, `email`, `email_verified`, `role`)

### Error envelope
```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```
`details` opcional.

### Claims JWT mínimos
- Requeridos: `sub`, `iss`, `aud`, `iat`, `exp`, `jti`
- Recomendados: `role`, `email_verified`

## Criterios de aceptación consolidados

1. Campos mínimos de Usuario definidos y alineados a login.
2. Login valida credenciales y devuelve éxito/error consistente.
3. Sesión/token generado correctamente (access + refresh).
4. Backend valida autenticación para rutas protegidas.
5. Flujo básico documentado y verificable.

## Entrega incremental (PRs chicos)

Estrategia: `feature-branch-chain`.

1. PR1: entidad user + puertos + reglas base.
2. PR2: register/login + emisión de access JWT.
3. PR3: refresh rotativo + logout invalidation + `/auth/me`.
4. PR4: adapter Postgres + wiring final + documentación.

## Riesgos principales

- Implementación incorrecta de rotación/reuse de refresh.
- Inconsistencia de códigos de error entre endpoints.
- Acoplamiento accidental de capa aplicación a SQL.

## Mitigaciones

- Definir invariantes en spec y tests de contrato por puerto.
- Normalizar taxonomía de errores desde el inicio.
- Revisiones arquitectónicas por PR para asegurar DB-agnostic.
