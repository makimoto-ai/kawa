# FAQ

Short answers to questions that come up often, drawn from the rest of this site. Follow the links for full detail.

## Requests, Limits, and Quota

### What audio formats are supported?

MP3 and WAV only; anything else returns `415 Unsupported Media Type`. See [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits).

### What's the maximum file size?

The limit is ≤ 10 MB per upload; larger files return `413 Payload Too Large`.

### How do I check my remaining quota?

You may check your remaining quota through the API via `GET /v1/transcriptions/usage` (see
[its reference](service/api-reference.md#get-v1transcriptionsusage), or through the developer portal at [makimoto.ai](https://makimoto.ai).

The free allowance is 1,000 minutes of audio per month.

### Do failed jobs count against my quota?

No. Per the quota constraint in [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits), failed jobs are not counted.

## Errors

### Why am I getting a `401`?

The bearer token is missing, expired, or revoked. See [Token Lifetime and Refresh](service/authentication.md#token-lifetime-and-refresh) for how tokens expire and how to get a fresh one.

### Why am I getting a `429`?

The account's monthly transcription-minute quota has been exceeded. Check `GET /v1/transcriptions/usage` to see how much is remaining.

### Why am I getting a `415`?

The uploaded file isn't MP3 or WAV. See [Supported Audio and Limits](service/api-reference.md#supported-audio-and-limits).

## Transcripts and Diarization

### How does speaker diarization work?

Diarization is currently stereo-only: the pipeline splits the two audio channels (left/right) and diarizes by channel, rather than separating speakers within a single mixed signal. 

See [Diarization](service/api-reference.md#diarization) for detail, including how each channel maps to a speaker index.

### Can I delete a transcription?

Yes, `DELETE /v1/transcriptions/{job_id}` removes the source audio from storage immediately and flags the job for scheduled deletion per the retention policy. See [its reference](service/api-reference.md#delete-v1transcriptionsjob_id).

## Access and Data

### Where is my data hosted?

All data is hosted in Singapore. See [Data Residency](concepts/index.md#data-residency) for how this supports Singapore's PDPA and MAS guidelines.

### Does Kawa support real-time transcription?

Not yet. The current API is post-conversation only (recorded calls, voicemail, archived interactions). 

A real-time API is planned; see [How It Works](concepts/index.md) and the [roadmap](https://github.com/makimoto-ai/kawa/blob/main/ROADMAP.md).
