# SCOUTAI-33 Register/Delete — Spec

## Requirement 1: Trazabilidad SDD mínima
El cambio **MUST** tener artefactos locales trazables con prefijo `scoutai-33-register-delete-*`.

### Scenario: Artefactos presentes
- **GIVEN** el repo en `feature/scoutai-auth`
- **WHEN** se inspecciona `specs/prd/`
- **THEN** existen proposal/spec/tasks/verify del cambio `scoutai-33-register-delete`

## Requirement 2: Pytest disponible en entorno del proyecto
El entorno `.venv` **MUST** poder ejecutar `pytest`.

### Scenario: Pytest instalado y pinneado
- **GIVEN** `requirements.txt`
- **WHEN** se instalan dependencias en `.venv`
- **THEN** `pytest` está disponible en `.venv/bin/python -m pytest`

## Requirement 3: Verify sin warnings originales
El verify report **MUST** reflejar resolución de warnings de trazabilidad y tooling.

### Scenario: Reporte actualizado
- **GIVEN** ejecución de tests relevantes
- **WHEN** se actualiza el reporte de verificación
- **THEN** no figuran los warnings por falta de artefactos ni por ausencia de `pytest`
