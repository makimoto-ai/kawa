# FAQ

*Last updated: 2026-09-15*

## Requests, Limits, and Quota

### What audio formats are supported?

MP3 and WAV only; anything else returns `415 Unsupported Media Type`. See [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits).

### What's the maximum file size?

The limit is ≤ 10 MB per upload; larger files return `413 Payload Too Large`.

### How do I check my remaining quota?

You may check your remaining quota through the developer portal at [makimoto.ai](https://makimoto.ai). `GET /v1/transcriptions/usage` reports the same figures, but it's authenticated with your dashboard sign-in session, not an API key, so an API-key client can't call it directly; track quota from the `error.details` on a `429 QUOTA_EXCEEDED` response instead. See the [note on `GET /v1/transcriptions/usage`](service/api-reference.md#get-v1transcriptionsusage) for detail.

The free allowance is 1,000 minutes of audio per month.

### Do failed jobs count against my quota?

No. Per the quota constraint in [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits), failed jobs are not counted.

## Errors

### Why am I getting a `401`?

The API key is missing, invalid, expired, or revoked. See [Key Lifetime and Rotation](service/authentication.md#key-lifetime-and-rotation) for how keys expire and how to issue a fresh one.

### Why am I getting a `429`?

The account's monthly transcription-minute quota has been exceeded (`QUOTA_EXCEEDED`). The error's `details` carry `limit_minutes`, `used_minutes`, and `file_minutes`, so you don't need a separate call to see how much is remaining. `GET /v1/transcriptions/usage` reports the same figures, but only to a dashboard sign-in session, not an API key; see [How do I check my remaining quota?](#how-do-i-check-my-remaining-quota) above.

### Why am I getting a `415`?

The uploaded file isn't MP3 or WAV. See [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits).

## Transcripts and Diarisation

### How does speaker diarisation work?

Diarisation is currently stereo-only: the pipeline splits the two audio channels (left/right) and diarises by channel, rather than separating speakers within a single mixed signal.

See [Diarisation](service/api-reference.md#diarisation) for detail, including how each channel maps to a speaker index.

### Can I delete a transcription?

Yes, `DELETE /v1/transcriptions/{job_id}` removes the source audio from storage immediately and flags the job for scheduled deletion per the retention policy. See [its reference](service/api-reference.md#delete-v1transcriptionsjob_id).

## Summaries and Tags

### Can I summarise or tag a transcription?

Yes. Once a transcription job has `succeeded`, call [`POST /v1/summarize`](service/api-reference.md#post-v1summarize) or [`POST /v1/tag`](service/api-reference.md#post-v1tag) with its `job_id`. Each returns a **new** job id; poll that one, not the transcription's.

### Can I summarise or tag plain text without transcribing audio first?

Yes. Pass `transcript_text` instead of `transcription_job_id` in the request body, and skip transcription entirely. Provide exactly one of the two; giving both, or neither, returns `400`.

### Why did my summarise or tag request return a `409`?

The source transcription hasn't reached `succeeded` yet (`TRANSCRIPTION_NOT_READY`). Poll the transcription until it finishes, then retry. This only applies to the `transcription_job_id` path; a `transcript_text` request has no transcription to wait on.

## Listing Jobs

### How do I page through a large number of jobs?

`GET /v1/transcriptions` returns 10 jobs per page by default (up to 100 with `?limit=`). Pass the `next_cursor` from one response back as `?cursor=` to fetch the next page; `next_cursor` is `null` once you've reached the last one. See [`GET /v1/transcriptions`](service/api-reference.md#get-v1transcriptions) for the full set of query parameters, including the `status`, `type`, `language`, `created_after`, and `job_id` filters.

## Access and Data

### Where is my data hosted?

All data is hosted in Singapore. See [Data Residency](concepts/index.md#data-residency) for how this supports Singapore's PDPA and MAS guidelines.

### Does Kawa support real-time transcription?

Not yet. The current API is post-conversation only (recorded calls, voicemail, archived interactions).

A real-time API is planned; see [How It Works](concepts/index.md) and the [roadmap](https://github.com/makimoto-ai/kawa/blob/main/ROADMAP.md).
