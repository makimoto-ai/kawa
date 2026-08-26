# API Reference

This page serves as a reference for all endpoints available for Kawa services.

You may also refer to [`openapi.json`](../openapi.json) in the Kawa repository.

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

### Status Codes

| Status | Meaning |
| --- | --- |
| `202` | Job accepted and submitted to the pipeline. |
| `400` | No audio file provided, or `metadata` is not valid JSON. |
| `401` | Missing or invalid bearer token. |
| `413` | File exceeds the 10 MB limit. |
| `415` | Unsupported audio format. Only MP3 and WAV are accepted. |
| `502` | The job was stored but submission to the pipeline failed. The job is marked `failed`. |
| `500` | Internal server error. |

Example `202` Response:

```json
{
  "job_id": "12cd73fe-182c-4040-a9d5-55b676d6e1c3",
  "status": "processing",
  "received_at": "2026-06-11T19:13:22.366Z"
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

Both single-channel (mono) and dual-channel (stereo) audio are accepted; see [Diarization](#diarization) below for how channel count affects speaker separation. 

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

### Diarization

Diarization is currently stereo-only: the pipeline splits the two channels (left/right) and diarizes by channel, rather than separating speakers within a single mixed signal. Each channel maps to a speaker index, labeled `speaker_id: 0` and `speaker_id: 1`.

---

## `GET /v1/transcriptions`

*List the caller's transcription jobs.*

Returns the caller's jobs, most recent first. Each item includes `job_id`, `status`, `original_filename`, `language`, `created_at`, and `updated_at`.

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `transcriptions` | Array of job summaries, most recent first. |
| `transcriptions[].job_id` | UUID identifying the job. |
| `transcriptions[].status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `transcriptions[].original_filename` | The uploaded file's original name. |
| `transcriptions[].language` | Requested/detected language, or `null` if not available. |
| `transcriptions[].created_at` | When the job was created (ISO 8601). |
| `transcriptions[].updated_at` | When the job was last updated (ISO 8601). |

### Status Codes

| Status | Meaning |
| --- | --- |
| `200` | List of the caller's jobs. |
| `401` | Missing or invalid bearer token. |
| `500` | Internal server error. |

Example `200` Response:

```json
{
  "transcriptions": [
    {
      "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
      "status": "succeeded",
      "original_filename": "harvard.wav",
      "language": "en",
      "created_at": "2026-07-01T09:15:23.412Z",
      "updated_at": "2026-07-01T09:15:41.902Z"
    }
  ]
}
```

---

## `GET /v1/transcriptions/usage`

*Get the caller's transcription usage.*

Returns the caller's transcription minute quota: total limit, minutes already consumed, and minutes remaining. Reflects the same quota state enforced on upload.

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `limit_minutes` | Total transcription minutes allowed. |
| `used_minutes` | Minutes already consumed (non-failed jobs). |
| `remaining_minutes` | Minutes still available. |

### Status Codes

| Status | Meaning |
| --- | --- |
| `200` | The caller's quota state. |
| `401` | Missing or invalid bearer token. |
| `500` | Internal server error. |

Example `200` Response:

```json
{
  "limit_minutes": 1000,
  "used_minutes": 12.5,
  "remaining_minutes": 987.5
}
```

---

## `GET /v1/transcriptions/{job_id}`

*Get a transcription job.*

Returns the specified job's status.

When `succeeded`, the response includes a `result` block (`language`, `duration_seconds`, `words_count`, `transcript` segments);
when `failed`, it includes an `error` block (`code`, `message`, and optionally a `provider_error`).

### Path Parameters

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. *Required.* |

### Response Body (`200`)

| Field | Description |
| --- | --- |
| `job_id` | UUID identifying the job. |
| `status` | Job lifecycle state (`queued`, `processing`, `succeeded`, `failed`). |
| `result` | Present when `status` is `succeeded`; see below. |
| `error` | Present when `status` is `failed`; see below. |

`result`:

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
| `speaker_id` | Numeric speaker index from diarization. |
| `speaker_alias` | Display label for the speaker. Current alias: `User`, `Agent` |

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
| `401` | Missing or invalid bearer token. |
| `403` | The job does not belong to the caller. |
| `404` | No job with that identifier. |
| `500` | Internal server error. |

Example `200` Response (`succeeded`):

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "succeeded",
  "result": {
    "language": "en",
    "duration_seconds": 18.4,
    "words_count": 48,
    "transcript": [
      { "text": "The birch canoe slid on the smooth planks.", "time_start": 0.0, "time_end": 3.1, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "Glue the sheet to the dark blue background.", "time_start": 3.4, "time_end": 6.6, "speaker_id": 0, "speaker_alias": "User" }
    ]
  }
}
```

Example `200` Response (`failed`):

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "failed",
  "error": {
    "code": "bad_audio",
    "message": "Unsupported audio format"
  }
}
```

---

## `DELETE /v1/transcriptions/{job_id}`

*Delete a transcription job.*

Removes the source audio from storage immediately and flags the job for scheduled deletion per the retention policy.

### Path Parameters

| Parameter | Description |
| --- | --- |
| `job_id` | UUID string. *Required.* |

### Status Codes

| Status | Meaning |
| --- | --- |
| `202` | Deletion accepted. Empty body. |
| `401` | Missing or invalid bearer token. |
| `403` | The job does not belong to the caller. |
| `404` | No job with that identifier. |
| `500` | Internal server error. |
