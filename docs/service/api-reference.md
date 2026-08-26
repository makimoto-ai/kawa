# API Reference

This page serves as a reference for all endpoints available for Kawa services. 

You may also refer to [`openapi.json`](../openapi.json) in the Kawa repository.

## `POST /v1/transcriptions`
<i>Create a transcription job.</i>

Upload an audio file (multipart/form-data, max 10 MB, MP3 or WAV only). The job is submitted to the transcription pipeline; the transcript is delivered asynchronously and retrieved via `GET /v1/transcriptions/{job_id}`.

**Request Body** (`multipart/form-data`)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary | Yes | Audio file to transcribe (max 10 MB). |
| `language` | string | No | Optional BCP-47 / ISO language hint, e.g. `en`. |
| `metadata` | string | No | Optional JSON-encoded object echoed back on the job. Must be a valid JSON string, e.g. `{"call_id":"abc-123"}`. |

**Responses**

| Status | Meaning |
| --- | --- |
| `202` | Job accepted and submitted to the pipeline. |
| `400` | No audio file provided, or `metadata` is not valid JSON. |
| `401` | Missing or invalid bearer token. |
| `413` | File exceeds the 10 MB limit. |
| `415` | Unsupported audio format. Only MP3 and WAV are accepted. |
| `502` | The job was stored but submission to the pipeline failed. The job is marked `failed`. |
| `500` | Internal server error. |

Example `202` response:

```json
{
  "job_id": "12cd73fe-182c-4040-a9d5-55b676d6e1c3",
  "status": "processing",
  "received_at": "2026-06-11T19:13:22.366Z"
}
```

---

## `GET /v1/transcriptions`
<i>List the caller's transcription jobs.</i>

Returns the caller's jobs, most recent first. Each item includes `job_id`, `status`, `original_filename`, `language`, `created_at`, and `updated_at`.

**Status Codes**

| Status | Meaning |
| --- | --- |
| `200` | List of the caller's jobs. |
| `401` | Missing or invalid bearer token. |
| `500` | Internal server error. |

---

## `GET /v1/transcriptions/usage`

<i>Get the caller's transcription usage.</i>

Returns the caller's transcription minute quota: total limit, minutes already consumed, and minutes remaining. Reflects the same quota state enforced on upload.

**Response Body**

| Field | Description |
| --- | --- |
| `limit_minutes` | Total transcription minutes allowed. |
| `used_minutes` | Minutes already consumed (non-failed jobs). |
| `remaining_minutes` | Minutes still available. |


**Status Codes**

| Status | Meaning |
| --- | --- |
| `200` | The caller's quota state. |
| `401` | Missing or invalid bearer token. |
| `500` | Internal server error. |

---

## `GET /v1/transcriptions/{job_id}`

<i>Get a transcription job.</i>

Returns the specified job's status. 

When `succeeded`, the response includes a `result` block (`language`, `duration_seconds`, `words_count`, `transcript` segments);
when `failed`, it includes an `error` block (`code`, `message`, and optionally a `provider_error`).

**Path Parameter** 

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. <i>Required.</i> |

**Status Codes**

| Status | Meaning |
| --- | --- |
| `200` | The job, with `result` (succeeded) or `error` (failed) when available. |
| `401` | Missing or invalid bearer token. |
| `403` | The job does not belong to the caller. |
| `404` | No job with that identifier. |
| `500` | Internal server error. |

---

## `DELETE /v1/transcriptions/{job_id}`

<i>Delete a transcription job.</i>

Removes the source audio from storage immediately and flags the job for scheduled deletion per the retention policy.

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. <i>Required.</i> |

**Status Codes**

| Status | Meaning |
| --- | --- |
| `202` | Deletion accepted. Empty body. |
| `401` | Missing or invalid bearer token. |
| `403` | The job does not belong to the caller. |
| `404` | No job with that identifier. |
| `500` | Internal server error. |

---