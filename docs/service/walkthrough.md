# Walkthrough

*Last updated: 2026-08-26*

A worked walkthrough from an API token to a finished transcript, using `curl` directly against the HTTP API. See [Authentication](authentication.md) for how tokens work and how long they last.

If you'd rather use Python, the same flow is available through the [`KawaClient` reference client](https://github.com/makimoto-ai/kawa/blob/main/demo/README.md#using-kawaclient) or the no-UI [`quickstart.py`](https://github.com/makimoto-ai/kawa/blob/main/demo/quickstart.py) script.

## 1. Create an Account

Create an account in the Makimoto dashboard:

```text
https://www.makimoto.ai/
```

After signing in, generate an API token from the developer/API section of the dashboard and set `MAKIMOTO_API_TOKEN`.

## 2. Authenticate and List Jobs

List jobs to verify access:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions" \
  -H "Authorization: Bearer ${MAKIMOTO_API_TOKEN}" | jq
```

Expected response for a new account:

```json
{
  "transcriptions": []
}
```

Once you have submitted jobs, the list will be populated with most recent first:

```json
{
  "transcriptions": [
    {
      "job_id": "b3f1c2a4-9d7e-4a1b-8c2f-1e5d6a7b8c90",
      "status": "succeeded",
      "original_filename": "harvard.wav",
      "language": "en",
      "created_at": "2026-07-01T09:15:23.412Z"
    }
  ]
}
```

## 3. Submit a Recording Upload

Upload an audio file as multipart form-data:

```bash
UPLOAD_RESPONSE="$(
  curl -sS -X POST "${MAKIMOTO_API_URL}/v1/transcriptions" \
    -H "Authorization: Bearer ${MAKIMOTO_API_TOKEN}" \
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
  -H "Authorization: Bearer ${MAKIMOTO_API_TOKEN}" | jq
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
