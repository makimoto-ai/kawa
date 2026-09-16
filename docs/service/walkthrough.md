# Walkthrough

*Last updated: 2026-09-16*

A worked walkthrough from an API key to a finished transcript, using `curl` directly against the HTTP API. See [Authentication](authentication.md) for how API keys work and how to rotate one.

If you'd rather use Python, the same flow is available through the [`KawaClient` reference client](https://github.com/makimoto-ai/kawa/blob/main/demo/README.md#using-kawaclient) or the no-UI [`quickstart.py`](https://github.com/makimoto-ai/kawa/blob/main/demo/quickstart.py) script.

## 1. Create an Account

Create an account in the Makimoto dashboard:

```text
https://www.makimoto.ai/
```

After signing in, create an API key from the developer/API section of the dashboard and set `MAKIMOTO_API_KEY` to it.

## 2. Authenticate and List Jobs

List jobs to verify access:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" | jq
```

Expected response for a new account:

```json
{
  "transcriptions": [],
  "next_cursor": null
}
```

Once you have submitted jobs, the list will be populated with most recent first:

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
      "created_at": "2026-07-01T09:15:23.412Z"
    }
  ],
  "next_cursor": null
}
```

The list is capped at 10 jobs per page by default (100 max) and cursor-paginated: pass `?limit=25` for a bigger page, and once a page is full, `next_cursor` carries the value to pass back as `?cursor=...` for the next one. It also accepts `status`, `type`, `language`, `created_after`, and `job_id` filters. See [`GET /v1/transcriptions`](api-reference.md#get-v1transcriptions) in the API Reference for the full set of query parameters.

## 3. Submit a Recording Upload

Upload an audio file as multipart form-data:

```bash
UPLOAD_RESPONSE="$(
  curl -sS -X POST "${MAKIMOTO_API_URL}/v1/transcriptions" \
    -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
    -F "file=@samples-audio/harvard.wav" \
    -F "language=en" \
    -F 'metadata={"source":"quickstart","external_id":"demo-001"}'
)"

printf "%s\n" "${UPLOAD_RESPONSE}" | jq
export MAKIMOTO_JOB_ID="$(printf "%s" "${UPLOAD_RESPONSE}" | jq -r ".job_id")"
```

Expected response:

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "queued",
  "received_at": "2026-07-01T09:15:23.412Z"
}
```

If a deployment rejects `language` as a top-level multipart field, leave it blank and include it in `metadata`, for example `{"language":"es"}`.

Full field reference, supported formats, size limits, and recommended encodings are in [`POST /v1/transcriptions`](api-reference.md#post-v1transcriptions) in the API Reference.

## 4. Check Job Status

Fetch one job:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/${MAKIMOTO_JOB_ID}" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" | jq
```

While the job runs, status moves from `queued` to `processing`:

```json
{
  "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
  "status": "processing"
}
```

Recommended polling behaviour:

- Poll `GET /v1/transcriptions/{job_id}` every 2 to 5 seconds while status is
  `queued` or `processing`.
- Stop when status is `succeeded` or `failed`.
- Treat `401` as missing, expired, or revoked credentials.
- Treat `403` as the job not belonging to the authenticated account.
- Treat `404` as an unknown job id.

## 5. Get Transcript

The transcript is returned from:

```http
GET /v1/transcriptions/{job_id}
```

When the job succeeds, the response includes `result`. This is the transcript of the bundled `samples-audio/harvard.wav`, a single speaker reading Harvard sentences:

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
      { "text": "Glue the sheet to the dark blue background.", "time_start": 3.4, "time_end": 6.6, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "It's easy to tell the depth of a well.", "time_start": 6.9, "time_end": 9.4, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "These days a chicken leg is a rare dish.", "time_start": 9.8, "time_end": 12.6, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "Rice is often served in round bowls.", "time_start": 13.0, "time_end": 15.4, "speaker_id": 0, "speaker_alias": "User" },
      { "text": "The juice of lemons makes fine punch.", "time_start": 15.8, "time_end": 18.4, "speaker_id": 0, "speaker_alias": "User" }
    ]
  }
}
```

Because `harvard.wav` is a single speaker, every segment is `User`.

For multi-speaker audio each segment carries the detected `speaker_id` and `speaker_alias`, so a two-party call alternates between `User` and `Agent`. For more on diarisation behaviour, see [Diarisation](api-reference.md#diarisation) in the API Reference.

When the job fails, the response includes `error`:

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

## 6. Summarise or Tag the Transcript

Once a transcription has `succeeded`, derive a summary or a tag set from it with [`POST /v1/summarize`](api-reference.md#post-v1summarize) or [`POST /v1/tag`](api-reference.md#post-v1tag). Both are asynchronous in the same way: the response is a **new** job id, which you poll like any other:

```bash
SUMMARY_RESPONSE="$(
  curl -sS -X POST "${MAKIMOTO_API_URL}/v1/summarize" \
    -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"transcription_job_id\":\"${MAKIMOTO_JOB_ID}\"}"
)"

printf "%s\n" "${SUMMARY_RESPONSE}" | jq
export MAKIMOTO_SUMMARY_JOB_ID="$(printf "%s" "${SUMMARY_RESPONSE}" | jq -r ".job_id")"
```

Expected response:

```json
{
  "job_id": "7e2b1a3c-4f5d-4e6a-9b8c-1d2e3f4a5b6c",
  "type": "summary",
  "status": "queued",
  "received_at": "2026-09-15T03:00:00.000Z"
}
```

You don't need a transcription job at all to use either endpoint: pass `transcript_text` with plain text instead of `transcription_job_id`, and the same pipeline summarises or tags it directly, with no audio or existing job involved:

```bash
curl -sS -X POST "${MAKIMOTO_API_URL}/v1/summarize" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"transcript_text":"Customer: I was charged twice for my last invoice.\nAgent: Let me pull that up and issue a refund."}' | jq
```

Provide exactly one of `transcription_job_id` or `transcript_text`; giving both, or neither, returns `400`.

Poll `MAKIMOTO_SUMMARY_JOB_ID` the same way as in step 4, then fetch it:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/${MAKIMOTO_SUMMARY_JOB_ID}" \
  -H "Authorization: Bearer ${MAKIMOTO_API_KEY}" | jq
```

Once it succeeds, `type` is `summary` and `result` carries `topic` and `summary` rather than a `transcript` array. `POST /v1/tag` works identically, except the resulting job's `type` is `tags` and `result.tags` holds the category/value pairs the pipeline selected. See [`GET /v1/transcriptions/{job_id}`](api-reference.md#get-v1transcriptionsjob_id) in the API Reference for both result shapes, and [`POST /v1/summarize`](api-reference.md#post-v1summarize) for the full set of postprocessing-specific error codes.
