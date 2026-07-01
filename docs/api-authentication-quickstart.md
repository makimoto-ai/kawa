# Makimoto API Authentication and Quickstart

This guide documents the developer flow for the Makimoto transcription API
during the beta.

## Authentication Model

Developers authenticate API requests with a token generated from the Makimoto
dashboard.

```http
Authorization: Bearer <makimoto_api_token>
```

Set these environment variables for the examples:

```bash
export MAKIMOTO_API_URL="https://api.makimoto.ai"
export MAKIMOTO_API_TOKEN="<token-from-dashboard>"
```

Generate the token from the dashboard. Public API integrations should not call
the underlying identity service directly; the dashboard handles sign-in and token
generation for you.

## Token Lifetime and Refresh

The dashboard token is short-lived. While you are signed in, the dashboard keeps
your token current, so for interactive and test usage you can copy the latest
token whenever you need one.

A token you have copied elsewhere (an environment variable, a script, a Postman
variable) is a snapshot: it does not renew itself and stops working once it
expires. When that happens, copy a fresh token from the dashboard. Treat any
`401` response from the API as "token missing, expired, or revoked" and
regenerate.

## Beta and Production Access

During the beta, access is token-based: retrieve a token from the dashboard at
[makimoto.ai](https://makimoto.ai) and send it as a bearer token, as shown above.
This suits development, testing, and the playground.

For production use, contact us at contact@makimoto.ai for persistent credentials
(such as an API key or other service authentication) and higher volume limits.

## 1. Create an Account

Create an account in the Makimoto dashboard:

```text
https://www.makimoto.ai/
```

After signing in, generate an API token from the developer/API section of the
dashboard and set `MAKIMOTO_API_TOKEN`.

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

## 3. Submit a Recording Upload

Upload an audio file as multipart form-data:

```bash
UPLOAD_RESPONSE="$(
  curl -sS -X POST "${MAKIMOTO_API_URL}/v1/transcriptions" \
    -H "Authorization: Bearer ${MAKIMOTO_API_TOKEN}" \
    -F "file=@samples-audio/audio.mp3" \
    -F "language=es" \
    -F 'metadata={"source":"quickstart","external_id":"demo-001"}'
)"

printf "%s\n" "${UPLOAD_RESPONSE}" | jq
export MAKIMOTO_JOB_ID="$(printf "%s" "${UPLOAD_RESPONSE}" | jq -r ".job_id")"
```

Expected response:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000000",
  "status": "queued",
  "received_at": "2026-06-30T00:00:00.000Z"
}
```

Request fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `file` | multipart file | yes | Audio file. |
| `language` | text | no | Sent as the API's multipart language field, for example `es`. |
| `metadata` | JSON string | no | Must be a valid JSON object when present. |

If a deployment rejects `language` as a top-level multipart field, leave it blank
and include it in `metadata`, for example `{"language":"es"}`.

## Supported Audio and Limits

| Constraint | Value | Response if exceeded |
| --- | --- | --- |
| Formats | MP3 and WAV only | `415 Unsupported Media Type` |
| Maximum file size | 10 MB per upload | `413 Payload Too Large` |
| Audio content | Must be decodable with a readable duration | `400 Bad Request` |
| Account quota | 1000 minutes of audio per month on the free allowance (failed jobs are not counted) | `429 Too Many Requests` |

Recommended encodings. Both single-channel (mono) and dual-channel (stereo) audio
are accepted; for call recordings where each speaker is on a separate channel,
stereo is useful. WAV should be 16-bit PCM. A sample rate of 8 kHz (telephone
band) up to 16 kHz is plenty for speech.

The 10 MB cap is reached at very different durations depending on encoding, so
choose the format to fit the clip:

| Encoding | Approx. minutes in 10 MB |
| --- | --- |
| WAV PCM 16-bit, 8 kHz, stereo | ~5.5 |
| WAV PCM 16-bit, 8 kHz, mono | ~11 |
| MP3 128 kbps | ~11 |
| MP3 32 kbps | ~44 |

For anything longer than a short clip, prefer MP3, or downmix WAV to mono, to stay
under the cap. The repository's `samples-audio/` directory contains ready-to-use
test files in the supported formats.

## 4. Check Job Status

Fetch one job:

```bash
curl -sS "${MAKIMOTO_API_URL}/v1/transcriptions/${MAKIMOTO_JOB_ID}" \
  -H "Authorization: Bearer ${MAKIMOTO_API_TOKEN}" | jq
```

Queued response:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000000",
  "status": "queued"
}
```

Recommended polling behavior:

- Poll `GET /v1/transcriptions/{job_id}` every 2 to 5 seconds while status is
  `queued` or `processing`.
- Stop when status is `succeeded` or `failed`.
- Treat `401` as missing, expired, or revoked credentials.
- Treat `403` as the job not belonging to the authenticated account.
- Treat `404` as an unknown job id.

## 5. Get Transcript

There is no separate transcript endpoint today. The transcript is returned from:

```http
GET /v1/transcriptions/{job_id}
```

When the job succeeds, the response includes `result`:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000000",
  "status": "succeeded",
  "result": {
    "language": "es",
    "duration_seconds": 42,
    "words_count": 120,
    "transcript": [
      {
        "text": "Hola, esta es una prueba.",
        "time_start": 0,
        "time_end": 2.4,
        "speaker_id": 0,
        "speaker_alias": "Speaker 0"
      }
    ]
  }
}
```

When the job fails, the response includes `error`:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000000",
  "status": "failed",
  "error": {
    "code": "bad_audio",
    "message": "Unsupported audio format"
  }
}
```

## References

- OpenAI API authentication: https://platform.openai.com/docs/api-reference/authentication
- Anthropic API authentication: https://docs.anthropic.com/en/api/getting-started
- Deepgram API authentication: https://developers.deepgram.com/docs/authenticating
