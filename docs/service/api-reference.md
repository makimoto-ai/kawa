---
description: Every Kawa API endpoint, with request and response formats, error codes and the OpenAPI specification.
---

# API Reference

*Last updated: 2026-10-13*

This page serves as a reference for all endpoints available for Kawa services.

The parameter, field and status code tables are generated from the [OpenAPI specification](../openapi.json) (`openapi.json`) each time the site is built, so they always match it. The examples and guidance between them are written by hand.

To try these endpoints without writing code, fork the [Kawa collection](https://www.postman.com/makimoto-ai/makimoto-kawa-api/collection/9muqmgc/makimoto-transcription-api) into your own Postman workspace. In your fork, set the `raw_api_key` collection variable to your API key; every request authenticates with it from there.

::: openapi POST /v1/transcriptions

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

::: openapi GET /v1/transcriptions

The cursor only encodes position, not which filters were active, so resend the same filter parameters on every paginated request, or the result set can shift partway through.

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

::: openapi GET /v1/transcriptions/{job_id}

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

::: openapi POST /v1/summarize

### Current Behaviour and Limitations

The current summary feature has two caveats to take note of during use: 
1. Sufficient context has to be provided to the summary in order for a summary to be generated. If the transcript provided is too short, the service may return an empty summmary instead. 
2. The summary feature is optimised for a two-party telephony conversation; further behaviour customisation is in the works for a future release.

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

::: openapi POST /v1/tag

### Current Behaviour and Limitations

The current tagging service is optimised for a two-party telephony conversation, in the context of a business-customer call. As such, the tags generated may reference terminology pertaining to this context. 

Tagging customisation is in the works for a future release.

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

::: openapi DELETE /v1/transcriptions/{job_id}

Example `202` Response:

```json
{
  "requestId": "e1f2a3b4-c5d6-4789-e0f1-a2b3c4d5e6f7"
}
```
