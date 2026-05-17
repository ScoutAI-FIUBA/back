# Endpoint Documentation Template

## Summary

- **Endpoint name**:
- **Purpose**:
- **Consumer(s)**:

## Contract

- **Method**: `GET | POST | PUT | PATCH | DELETE`
- **Path**: `/api/...`
- **Version**: `v1` (or applicable)
- **Auth**: `None | Bearer JWT | API Key | Session`
- **Idempotency**: `Yes/No` (if relevant)

## Request

### Path params

| Name | Type | Required | Description | Example |
|---|---|---|---|---|
| | | | | |

### Query params

| Name | Type | Required | Default | Description | Example |
|---|---|---|---|---|---|
| | | | | | |

### Headers

| Header | Required | Description | Example |
|---|---|---|---|
| `Authorization` | Yes/No | | `Bearer <token>` |

### Request body

Schema (JSON-like):

```json
{
  "field": "type"
}
```

Example request:

```bash
curl -X POST 'https://api.example.com/api/...' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  -d '{"field":"value"}'
```

## Response

### Success response

- **Status**: `200 | 201 | 204`

Example:

```json
{
  "data": {}
}
```

### Response fields

| Field | Type | Nullable | Description |
|---|---|---|---|
| | | | |

## Status codes

| Code | Meaning | When |
|---|---|---|
| 200 | OK | |
| 201 | Created | |
| 204 | No Content | |
| 400 | Bad Request | |
| 401 | Unauthorized | |
| 403 | Forbidden | |
| 404 | Not Found | |
| 409 | Conflict | |
| 422 | Unprocessable Entity | |
| 500 | Internal Server Error | |

## Error format

Example:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "details": [
      {
        "field": "email",
        "reason": "invalid format"
      }
    ],
    "requestId": "req_123"
  }
}
```

## Frontend integration notes

- Caching guidance:
- Retry guidance:
- Empty/loading/error states:
- Backward compatibility considerations:
