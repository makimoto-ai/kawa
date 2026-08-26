# Service

Reference documentation for the Kawa transcription API itself: how to authenticate, the endpoints available, and their limits.

- **[Authentication and quickstart](authentication.md)** — the token model, a worked request/response walkthrough, supported audio formats, and size limits.
- **[OpenAPI specification](../openapi.json)** — the full HTTP contract in machine-readable form.

## Endpoints at a glance

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/v1/transcriptions` | Submit audio (multipart); returns a job id |
| `GET` | `/v1/transcriptions` | List your jobs |
| `GET` | `/v1/transcriptions/{job_id}` | Job status, and the transcript once done |
| `DELETE` | `/v1/transcriptions/{job_id}` | Remove a job (where supported) |

Every request is authenticated with `Authorization: Bearer <token>`; see [Authentication and quickstart](authentication.md) for how to obtain and use one.
