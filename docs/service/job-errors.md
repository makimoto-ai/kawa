---
description: What each Kawa job error code means, why it happens and what to do next.
---

# Job Errors

*Last updated: 2026-10-29*

A job that fails has `status: "failed"` and an `error` object, on [`GET /v1/transcriptions/{job_id}`](api-reference.md#get-v1transcriptionsjob_id) and on each failed row of [`GET /v1/transcriptions`](api-reference.md#get-v1transcriptions):

```json
"error": {
  "code": "invalid_audio",
  "message": "The audio could not be decoded.",
  "next_step": "Check that the file is a complete recording in a supported audio format, then submit it again.",
  "docs_url": "https://docs.makimoto.ai/service/job-errors/#invalid_audio"
}
```

- Match on `code`, not on `message`: the wording may change.
- `message` and `next_step` are written to be shown to your users as they are.
- `docs_url` links to the code's entry below.
- New codes may be added. Treat a code not listed here as a generic failure; its `docs_url` points to this page.
- `provider_error`, when present, is the processing service's own code and message, kept for Makimoto support. It may change without notice; don't match on it.

These are errors on a job that was created. A request refused before any job exists (a bad API key, an unsupported format, the quota used up) returns an HTTP error instead; see each endpoint's status codes in the [API Reference](api-reference.md).

## Transcription

### `invalid_audio` {#invalid_audio}

**The audio could not be decoded.**

The file was received but isn't readable audio: it is corrupt, cut short, or not really MP3 or WAV.

**Next step:** Check that the file is a complete recording in a supported audio format, then submit it again.

### `provider_no_transcript` {#provider_no_transcript}

**The transcription could not be completed.**

Transcription failed for a reason not covered by another code, or finished without any speech to transcribe.

**Next step:** Check that the recording contains speech, then submit it again. If it fails again, report the problem with the job ID.

### `transcription_timeout` {#transcription_timeout}

**Transcription took too long and was stopped.**

The recording ran past the processing time limit, even after one automatic retry.

**Next step:** Try a shorter recording, or split a long one into parts. If a short recording times out, report the problem with the job ID.

### `unsupported_language` {#unsupported_language}

**The requested language is not supported.**

The `language` set on the request isn't a code the transcription service accepts. Regional forms such as `en-US` are not accepted.

**Next step:** Use an ISO 639-1 language code such as `en`, or leave the language out to have it detected.

## Summaries and Tags

### `no_summary` {#no_summary}

**No summary could be made from this transcript.**

The transcript had nothing the model could summarise.

**Next step:** This is a result, not a fault: retrying the same transcript gives the same answer.

### `no_tags` {#no_tags}

**No tags could be found in this transcript.**

None of the tag categories matched the transcript.

**Next step:** This is a result, not a fault: retrying the same transcript gives the same answer.

### `provider_postprocessing_failed` {#provider_postprocessing_failed}

**The summary or tags could not be produced.**

The summarisation service failed, even after automatic retries.

**Next step:** Submit the request again. If it fails again, report the problem with the job ID.

## Any Job

### `provider_submit_failed` {#provider_submit_failed}

**The job could not be sent for processing.**

The job was saved but couldn't be handed to the processing service. When this happens while the job is being created, the request itself returns HTTP `502` with the code `PROVIDER_SUBMIT_FAILED`, and the job is saved with this code.

**Next step:** Submit the job again in a few minutes. If it keeps failing, report the problem with the job ID.

### `queue_timeout` {#queue_timeout}

**Job waited too long in the queue without being sent.**

The job was never sent for processing.

**Next step:** Submit the job again. If it keeps happening, report the problem with the job ID.

### `reconciliation_timeout` {#reconciliation_timeout}

**Job exceeded the maximum time allowed without a provider callback.**

The job was sent for processing, but no result came back in time.

**Next step:** Submit the job again. If it keeps happening, report the problem with the job ID.
