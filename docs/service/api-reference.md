# API Reference

*Last updated: 2026-09-17*

This page serves as a reference for all endpoints available for Kawa services.

You may also refer to [`openapi.json`](https://github.com/makimoto-ai/kawa/blob/main/docs/openapi.json) in the Kawa repository.

## `POST /v1/transcriptions`

*Create a transcription job.*

Upload an audio file (multipart/form-data, max 10 MB, MP3 or WAV only). The job is submitted to the transcription pipeline; the transcript is delivered asynchronously and retrieved via `GET /v1/transcriptions/{job_id}`.

### Request Body (`multipart/form-data`)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary | Yes | Audio file to transcribe (max 10 MB). |
| `language` | string | No | Optional BCP-47 / ISO language hint, e.g. `en`. |
| `metadata` | string | No | Optional JSON-encoded object echoed back on the job. Must be a valid JSON string, e.g. `{"call_id":"abc-123"}`. |

### Response Body (`202`)

| Field | Description |
| --- | --- |
| `job_id` | UUID identifying the job. |
| `status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `received_at` | Timestamp the upload was received (ISO 8601). |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `202` | Job accepted and submitted to the pipeline. |
| `400 AUDIO_FILE_MISSING` | No audio file provided. |
| `400 AUDIO_DURATION_UNKNOWN` | The audio was received but its duration couldn't be determined. |
| `400 INVALID_METADATA_JSON` | `metadata` is not a valid JSON string. |
| `401` | Missing or invalid API key. |
| `413 FILE_TOO_LARGE` | File exceeds the 10 MB limit. |
| `415 UNSUPPORTED_AUDIO_FORMAT` | Unsupported audio format. Only MP3 and WAV are accepted. |
| `429 QUOTA_EXCEEDED` | This upload would push the account over its monthly transcription-minute quota. |
| `500` | Internal server error. |
| `502 PROVIDER_SUBMIT_FAILED` | The job was stored but submission to the pipeline failed. The job is marked `failed`. |

### Example

Request:

```bash
curl -sS -X POST "${MAKIMOTO_API_URL}/v1/transcriptions" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
  -F "file=@samples-audio/harvard.wav" \
  -F "language=en" \
  -F 'metadata={"call_id":"abc-123"}'
```

Success (`202`):

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "processing",
  "received_at": "2026-07-01T09:15:23.412Z",
  "requestId": "a1b2c3d4-e5f6-4789-a0b1-c2d3e4f5a6b7"
}
```

Poll for the result:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}"
```

Succeeded (`200`), once the transcript is ready:

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "succeeded",
  "type": "transcription",
  "result": {
    "language": "en",
    "duration_seconds": 18,
    "words_count": 48,
    "transcript": [
      { "text": "The birch canoe slid on the smooth planks.", "time_start": 0.0, "time_end": 3.1, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "Glue the sheet to the dark blue background.", "time_start": 3.4, "time_end": 6.6, "speaker_id": 0, "speaker_alias": "User" }
    ]
  },
  "requestId": "d4e5f6a7-b8c9-4012-d3e4-f5a6b7c8d9e0"
}
```

Failure (`415 UNSUPPORTED_AUDIO_FORMAT`), for example uploading an `.m4a` file:

```json
{
  "error": { "code": "UNSUPPORTED_AUDIO_FORMAT", "message": "Unsupported audio format. Only MP3 and WAV are accepted." },
  "requestId": "b2c3d4e5-f6a7-4890-b1c2-d3e4f5a6b7c8"
}
```

Every error response carries this same envelope: a machine-readable `code` and `message`, plus the same top-level `requestId` as a successful one. `QUOTA_EXCEEDED` also carries `error.details`:

```json
{
  "error": { "code": "QUOTA_EXCEEDED", "message": "Transcription minute quota exceeded.", "details": { "limit_minutes": 1000, "used_minutes": 998.2, "file_minutes": 5.0 } },
  "requestId": "d4e5f6a7-b8c9-40d1-92e3-f4a5b6c7d8e9"
}
```

---

### Supported Audio and Limits

| Constraint | Value | Response if exceeded |
| --- | --- | --- |
| Formats | MP3 and WAV only | `415 Unsupported Media Type` |
| Maximum file size | 10 MB per upload | `413 Payload Too Large` |
| Audio content | Must be decodable with a readable duration | `400 Bad Request` |
| Account quota | 1000 minutes of audio per month on the free allowance (failed jobs are not counted) | `429 Too Many Requests` |

Both single-channel (mono) and dual-channel (stereo) audio are accepted; see [Diarisation](#diarisation) below for how channel count affects speaker separation. 

!!! note 
    A supposed single-speaker mono audio file can actually be a stereo audio file, with mono audio duplicated in both channels (conversion could happen when downloading the audio, for instance). Therefore, the output may appear duplicated for both speakers, when there is only one speaker in the audio.

Recommended encoding: WAV, 16-bit PCM, at a sample rate between 8 kHz (telephone band) and 16 kHz, which is plenty for speech.

The 10 MB cap is reached at very different durations depending on encoding, so choose the format to fit the clip:

| Encoding | Approx. minutes in 10 MB |
| --- | --- |
| WAV PCM 16-bit, 8 kHz, stereo | ~5.5 |
| WAV PCM 16-bit, 8 kHz, mono | ~11 |
| MP3 128 kbps | ~11 |
| MP3 32 kbps | ~44 |

!!! tip
    For anything longer than a short clip, try using MP3 or downmix WAV to mono to stay under the cap. The repository's `samples-audio/` directory contains ready-to-use test files in the supported formats.

### Diarisation

Diarisation is currently stereo-only: the pipeline splits the two channels (left/right) and diarises by channel, rather than separating speakers within a single mixed signal. Each channel maps to a speaker index, labeled `speaker_id: 0` and `speaker_id: 1`.

---

## `GET /v1/transcriptions`

*List the caller's transcription jobs.*

Returns the caller's jobs, most recent first, mixing transcriptions with any `summary` or `tags` jobs derived from them. The list is cursor-paginated and filterable; filters compose with AND when combined.

### Query Parameters

| Parameter | Required | Description |
| --- | --- | --- |
| `limit` | No | Max jobs to return. Default `10`, max `100`; values above `100` are silently capped rather than rejected. A non-numeric or non-positive value returns `400`. |
| `cursor` | No | Opaque pagination cursor from a previous response's `next_cursor`. Omit for the first page. Not meant to be constructed or decoded by clients; its internal shape may change. A malformed cursor returns `400` rather than silently restarting at page one. |
| `status` | No | Only return jobs with this status (`queued`, `processing`, `succeeded`, `failed`). |
| `type` | No | Only return jobs of this type (`transcription`, `summary`, `tags`). |
| `language` | No | Only return jobs with this exact language value, e.g. `en`. |
| `created_after` | No | Only return jobs created after this ISO 8601 timestamp, e.g. `2026-06-01T00:00:00Z`. |
| `job_id` | No | Only return the job with this exact UUID. An exact match, not a search; a malformed UUID returns `400`. |

The cursor only encodes position, not which filters were active, so resend the same filter parameters on every paginated request, or the result set can shift partway through.

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `transcriptions` | Array of job summaries, most recent first. |
| `transcriptions[].job_id` | UUID identifying the job. |
| `transcriptions[].type` | `transcription`, `summary`, or `tags`. |
| `transcriptions[].status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `transcriptions[].original_filename` | The uploaded file's original name, or `null` if the job's upload hasn't been attached yet. |
| `transcriptions[].language` | Requested/detected language, or `null` if not available. |
| `transcriptions[].audio_seconds` | Audio duration in seconds. `0` for a `summary` or `tags` job, whose seconds were already metered by the transcription it was derived from. |
| `transcriptions[].created_at` | When the job was created (ISO 8601). |
| `transcriptions[].updated_at` | When the job was last updated (ISO 8601). |
| `next_cursor` | Opaque cursor for the next page, or `null` if this is the last page. Pass it back as `cursor` to continue. |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `200` | List of the caller's jobs. |
| `400 INVALID_PAGINATION` | `limit` isn't a positive integer, or `cursor` is malformed. |
| `400 INVALID_FILTER` | `status`, `type`, `job_id`, or `created_after` fails validation (bad enum value, non-UUID, or unparseable timestamp). |
| `401` | Missing or invalid API key. |
| `500` | Internal server error. |

Example `200` Response (a single job, well within the default `limit` of 10):

```json
{
  "transcriptions": [
    {
      "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
      "type": "transcription",
      "status": "succeeded",
      "original_filename": "harvard.wav",
      "language": "en",
      "audio_seconds": 18,
      "created_at": "2026-07-01T09:15:23.412Z",
      "updated_at": "2026-07-01T09:15:41.902Z"
    }
  ],
  "next_cursor": null,
  "requestId": "b2c3d4e5-f6a7-4890-b1c2-d3e4f5a6b7c8"
}
```

Example request for the next page of a larger list, filtered to succeeded transcriptions only:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions?status=succeeded&type=transcription&limit=25&cursor=${NEXT_CURSOR}" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" | jq
```

---

## `GET /v1/transcriptions/usage`

*Get the caller's transcription usage.*

Returns the caller's transcription minute quota: total limit, minutes already consumed, and minutes remaining. Reflects the same quota state enforced on upload.

!!! note
    Unlike every other endpoint on this page, this one is authenticated with your **dashboard sign-in session**, not an API key: it's a status view for the logged-in dashboard, not part of the API-key surface external clients use. An `Authorization: Bearer <api-key>` header gets `401` here. If you need quota programmatically from an API-key client, track it yourself from `429 QUOTA_EXCEEDED` responses on [`POST /v1/transcriptions`](#post-v1transcriptions) (its `error.details` carries `limit_minutes` and `used_minutes`); otherwise check the dashboard.

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `limit_minutes` | Total transcription minutes allowed. |
| `used_minutes` | Minutes already consumed (non-failed jobs). |
| `remaining_minutes` | Minutes still available. |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `200` | The caller's quota state. |
| `401` | Missing or invalid dashboard session. |
| `500` | Internal server error. |

Example `200` Response:

```json
{
  "limit_minutes": 1000,
  "used_minutes": 12.5,
  "remaining_minutes": 987.5,
  "requestId": "c3d4e5f6-a7b8-4901-c2d3-e4f5a6b7c8d9"
}
```

---

## `GET /v1/transcriptions/{job_id}`

*Get a job.*

Returns the specified job's status. This endpoint serves all three job kinds: a transcription itself, and the `summary` or `tags` jobs derived from one via [`POST /v1/summarize`](#post-v1summarize) and [`POST /v1/tag`](#post-v1tag) below.

When `succeeded`, the response includes a `result` block, shaped according to `type` (see below); when `failed`, it includes an `error` block (`code`, `message`, and optionally a `provider_error`).

### Path Parameters

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. *Required.* |

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `job_id` | UUID identifying the job. |
| `status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `type` | `transcription`, `summary`, or `tags`. Absent on jobs created before this field existed; treat a missing `type` as `transcription`. |
| `source_job_id` | For a `summary` or `tags` job, the `job_id` of the transcription it was derived from. **Omitted entirely** (not `null`) on a transcription, and on a postprocessing job created before the API began recording the pairing. |
| `result` | Present when `status` is `succeeded`; shape depends on `type`, see below. |
| `error` | Present when `status` is `failed`; see below. |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

`result` when `type` is `transcription`:

| Field | Description |
| --- | --- |
| `language` | Detected language, or `null` if not available. |
| `duration_seconds` | Audio duration in seconds. |
| `words_count` | Word count of the transcript, or `null` if not available. |
| `transcript` | Array of speaker-attributed segments; see below. |

`transcript[]` (one entry per segment):

| Field | Description |
| --- | --- |
| `text` | The segment's transcribed text. |
| `time_start` | Segment start, in seconds. |
| `time_end` | Segment end, in seconds. |
| `speaker_id` | Numeric speaker index from diarisation. |
| `speaker_alias` | Display label for the speaker. Current alias: `User`, `Agent` |

`result` when `type` is `summary`:

| Field | Description |
| --- | --- |
| `topic` | Short label for what the conversation was about, or `null`. |
| `summary` | Prose summary of the transcription. |
| `meta_data` | Optional free-form object echoed back by the pipeline, or `null`. |

`result` when `type` is `tags`:

| Field | Description |
| --- | --- |
| `tags` | Object mapping a fixed, `lower_snake_case` category (`call_reason`, `call_outcome`, …) to the array of values selected for it. The taxonomy is fixed by the service, not configurable per account. |
| `meta_data` | Optional free-form object echoed back by the pipeline, or `null`. |

`error`:

| Field | Description |
| --- | --- |
| `code` | Machine-readable error code, e.g. `bad_audio`. |
| `message` | Human-readable error message. |
| `provider_error` | Optional nested `code`/`message` from the underlying transcription provider, when available. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `200` | The job, with `result` (succeeded) or `error` (failed) when available. |
| `400 MISSING_JOB_ID` | No `job_id` in the path. Not reachable through a normal request to this route; only a malformed client call triggers it. |
| `401` | Missing or invalid API key. |
| `403 FORBIDDEN` | The job does not belong to the caller. |
| `404 JOB_NOT_FOUND` | No job with that identifier. |
| `500` | Internal server error. |

Example `200` Response (`succeeded`, `type: transcription`):

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "succeeded",
  "type": "transcription",
  "result": {
    "language": "en",
    "duration_seconds": 18,
    "words_count": 48,
    "transcript": [
      { "text": "The birch canoe slid on the smooth planks.", "time_start": 0.0, "time_end": 3.1, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "Glue the sheet to the dark blue background.", "time_start": 3.4, "time_end": 6.6, "speaker_id": 0, "speaker_alias": "User" }
    ]
  },
  "requestId": "d4e5f6a7-b8c9-4012-d3e4-f5a6b7c8d9e0"
}
```

Example `200` Response (`succeeded`, `type: summary`):

```json
{
  "job_id": "7e2b1a3c-4f5d-4e6a-9b8c-1d2e3f4a5b6c",
  "status": "succeeded",
  "type": "summary",
  "source_job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "result": {
    "topic": "Billing dispute",
    "summary": "Customer called about a duplicate charge on their latest invoice; agent confirmed the refund and closed the ticket.",
    "meta_data": null
  },
  "requestId": "e5f6a7b8-c9d0-4123-e4f5-a6b7c8d9e0f1"
}
```

Example `200` Response (`succeeded`, `type: tags`):

```json
{
  "job_id": "9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
  "status": "succeeded",
  "type": "tags",
  "source_job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "result": {
    "tags": {
      "call_reason": ["billing_issue", "refund"],
      "call_outcome": ["issue_resolved"]
    },
    "meta_data": null
  },
  "requestId": "f6a7b8c9-d0e1-4234-f5a6-b7c8d9e0f1a2"
}
```

Example `200` Response (`failed`):

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "failed",
  "type": "transcription",
  "error": {
    "code": "bad_audio",
    "message": "Unsupported audio format"
  },
  "requestId": "a7b8c9d0-e1f2-4345-a6b7-c8d9e0f1a2b3"
}
```

---

## `POST /v1/summarize`

*Summarise a transcription.*

Derives a topic and prose summary either from one of your own transcription jobs, or from plain text supplied directly. No audio is involved and nothing is generated synchronously: the call returns a new `summary` job immediately, which you poll like any other job via [`GET /v1/transcriptions/{job_id}`](#get-v1transcriptionsjob_id).

### Current Behaviour and Limitations

The current summary feature has two caveats to take note of during use: 
1. Sufficient context has to be provided to the summary in order for a summary to be generated. If the transcript provided is too short, the service may return an empty summmary instead. 
2. The summary feature is optimised for a two-party telephony conversation; further behaviour customisation is in the works for a future release.

### Request Body (`application/json`)

Provide **exactly one** of `transcription_job_id` or `transcript_text`.

| Field | Type | Description |
| --- | --- | --- |
| `transcription_job_id` | string (UUID) | `job_id` of a **transcription** job in status `succeeded`. |
| `transcript_text` | string | A transcript supplied directly as plain text, with no transcription job behind it. Skips the ownership/status checks that apply to `transcription_job_id`, since there is no job to check. |

```json
{ "transcript_text": "Customer: I was charged twice for my last invoice.\nAgent: Let me pull that up and issue a refund." }
```

### Response Body (`202`)

| Field | Description |
| --- | --- |
| `job_id` | UUID identifying the new `summary` job. **Poll this id**, not `transcription_job_id`. |
| `type` | Always `summary` for this endpoint. |
| `status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `received_at` | Timestamp the request was received (ISO 8601). |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `202` | Job accepted. |
| `400 INVALID_JSON_BODY` | The request body isn't valid JSON. |
| `400 MISSING_TRANSCRIPT_SOURCE` | Neither `transcription_job_id` nor `transcript_text` was given. |
| `400 MULTIPLE_TRANSCRIPT_SOURCES` | Both `transcription_job_id` and `transcript_text` were given; provide exactly one. |
| `400 NOT_A_TRANSCRIPTION` | `transcription_job_id` refers to a `summary` or `tags` job, not a transcription. |
| `401` | Missing or invalid API key. |
| `403 FORBIDDEN` | `transcription_job_id` belongs to a different caller. |
| `404 JOB_NOT_FOUND` | `transcription_job_id` doesn't exist. |
| `409 TRANSCRIPTION_NOT_READY` | The source transcription exists but has not yet succeeded. Retry once it has. Only applies to the `transcription_job_id` path. |
| `422 TRANSCRIPT_EMPTY` | The source transcription succeeded, but there was no speech to summarise. Only applies to the `transcription_job_id` path: empty or whitespace-only `transcript_text` is treated as not provided at all, and returns `400 MISSING_TRANSCRIPT_SOURCE` instead. |
| `500` | Internal server error. |
| `502 PROVIDER_SUBMIT_FAILED` | The job was stored but submission to the summarisation provider failed. The job is marked `failed`. |

### Example

Request, using `transcript_text` directly (no transcription job involved):

```bash
curl -sS -X POST "${MAKIMOTO_API_URL}/v1/summarize" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"transcript_text":"Customer: I was charged twice for my last invoice.\nAgent: Let me pull that up and issue a refund."}'
```

Or, derived from an already-succeeded transcription job:

```bash
curl -sS -X POST "${MAKIMOTO_API_URL}/v1/summarize" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"transcription_job_id":"b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90"}'
```

Success (`202`):

```json
{
  "job_id": "7e2b1a3c-4f5d-4e6a-9b8c-1d2e3f4a5b6c",
  "type": "summary",
  "status": "queued",
  "received_at": "2026-09-15T03:00:00.000Z",
  "requestId": "c9d0e1f2-a3b4-4567-c8d9-e0f1a2b3c4d5"
}
```

Poll for the result:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/7e2b1a3c-4f5d-4e6a-9b8c-1d2e3f4a5b6c" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}"
```

Succeeded (`200`):

```json
{
  "job_id": "7e2b1a3c-4f5d-4e6a-9b8c-1d2e3f4a5b6c",
  "status": "succeeded",
  "type": "summary",
  "source_job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "result": {
    "topic": "Billing dispute",
    "summary": "Customer called about a duplicate charge on their latest invoice; agent confirmed the refund and closed the ticket.",
    "meta_data": null
  },
  "requestId": "e5f6a7b8-c9d0-4123-e4f5-a6b7c8d9e0f1"
}
```

Failure (`409 TRANSCRIPTION_NOT_READY`), if `transcription_job_id` points at a transcription still `queued` or `processing`:

```json
{
  "error": { "code": "TRANSCRIPTION_NOT_READY", "message": "The transcription has not succeeded yet.", "details": { "status": "processing" } },
  "requestId": "b8c9d0e1-f2a3-4456-b7c8-d9e0f1a2b3c4"
}
```

Every error response carries this same envelope: a machine-readable `code` and `message`, plus the same top-level `requestId` as a successful one.

---

## `POST /v1/tag`

*Tag a transcription.*

Same contract as [`POST /v1/summarize`](#post-v1summarize) above, including the `transcription_job_id` / `transcript_text` choice, except the derived job's `type` is `tags`, and its `result.tags` maps each category in the pipeline's fixed taxonomy (`call_reason`, `call_outcome`, …) to the values selected for this transcript.

### Current Behaviour and Limitations
The current tagging service is optimised for a two-party telephony conversation, in the context of a business-customer call. As such, the tags generated may reference terminology pertaining to this context. 

Tagging customisation is in the works for a future release.

### Request Body (`application/json`)

Provide **exactly one** of `transcription_job_id` or `transcript_text`.

| Field | Type | Description |
| --- | --- | --- |
| `transcription_job_id` | string (UUID) | `job_id` of a **transcription** job in status `succeeded`. |
| `transcript_text` | string | A transcript supplied directly as plain text, with no transcription job behind it. |

```json
{ "transcription_job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90" }
```

### Response Body (`202`)

| Field | Description |
| --- | --- |
| `job_id` | UUID identifying the new `tags` job. **Poll this id**, not `transcription_job_id`. |
| `type` | Always `tags` for this endpoint. |
| `status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `received_at` | Timestamp the request was received (ISO 8601). |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. |

### Status Codes

Same as `POST /v1/summarize` above: `202`, `400 INVALID_JSON_BODY`, `400 MISSING_TRANSCRIPT_SOURCE`, `400 MULTIPLE_TRANSCRIPT_SOURCES`, `400 NOT_A_TRANSCRIPTION`, `401`, `403 FORBIDDEN`, `404 JOB_NOT_FOUND`, `409 TRANSCRIPTION_NOT_READY`, `422 TRANSCRIPT_EMPTY`, `500`, `502 PROVIDER_SUBMIT_FAILED`.

### Example

Request, tagging an already-succeeded transcription job:

```bash
curl -sS -X POST "${MAKIMOTO_API_URL}/v1/tag" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"transcription_job_id":"b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90"}'
```

Success (`202`):

```json
{
  "job_id": "9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
  "type": "tags",
  "status": "queued",
  "received_at": "2026-09-15T03:00:05.000Z",
  "requestId": "d0e1f2a3-b4c5-4678-d9e0-f1a2b3c4d5e6"
}
```

Poll for the result:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}"
```

Succeeded (`200`):

```json
{
  "job_id": "9c8b7a6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
  "status": "succeeded",
  "type": "tags",
  "source_job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "result": {
    "tags": {
      "call_reason": ["billing_issue", "refund"],
      "call_outcome": ["issue_resolved"]
    },
    "meta_data": null
  },
  "requestId": "f6a7b8c9-d0e1-4234-f5a6-b7c8d9e0f1a2"
}
```

Failure (`422 TRANSCRIPT_EMPTY`), if the source transcription succeeded but had no speech to tag:

```json
{
  "error": { "code": "TRANSCRIPT_EMPTY", "message": "The transcription contains no speech to postprocess." },
  "requestId": "f1a2b3c4-d5e6-4789-a0b1-c2d3e4f5a6b7"
}
```

Every error response carries this same envelope: a machine-readable `code` and `message`, plus the same top-level `requestId` as a successful one.

---

## `DELETE /v1/transcriptions/{job_id}`

*Delete a transcription job.*

Removes the source audio from storage immediately and flags the job for scheduled deletion per the retention policy.

### Path Parameters

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. *Required.* |

### Response Body (`202`)

| Field | Description |
| --- | --- |
| `requestId` | Identifier for this request. Include it when contacting support about a specific call. The only field in the body; there is no other confirmation payload. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `202` | Deletion accepted. |
| `400 MISSING_JOB_ID` | No `job_id` in the path. Not reachable through a normal request to this route; only a malformed client call triggers it. |
| `401` | Missing or invalid API key. |
| `403 FORBIDDEN` | The job does not belong to the caller. |
| `404 JOB_NOT_FOUND` | No job with that identifier. |
| `500` | Internal server error. |

Example `202` Response:

```json
{
  "requestId": "e1f2a3b4-c5d6-4789-e0f1-a2b3c4d5e6f7"
}
```
