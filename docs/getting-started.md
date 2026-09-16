# Getting Started

*Last updated: 2026-09-16*

This page gets you from no account to a finished transcript. Use this as a quickstart to get familiar with the API and services. 

## 1. Create an account

To begin, create an account at [makimoto.ai](https://makimoto.ai). Every account includes a free monthly allowance of 1,000 minutes of audio.

## 2. Generate an API key

Create an API key from the developer/API section of the dashboard. See [Authentication](service/authentication.md) for how API keys work and how to rotate one.

## 3. Try it

There are two ways to make your first call:

- **In your browser**, with the [playground](https://github.com/makimoto-ai/kawa/tree/main/demo): pick a sample recording, submit it, and read the transcript, with the exact `curl` shown for every call.

- **In code**, with the [`quickstart.py`](https://github.com/makimoto-ai/kawa/blob/main/demo/quickstart.py) script or the [`KawaClient`](https://github.com/makimoto-ai/kawa/blob/main/demo/kawa_client.py) reference client, a small, fully typed client that depends only on `requests`.

## 4. Submit, poll, and read a transcript

The full request and response flow, including supported audio formats and size limits, is in [Walkthrough](service/walkthrough.md).

In short:

1. `POST /v1/transcriptions` with the audio file, to get a `job_id`.
2. `GET /v1/transcriptions/{job_id}` every few seconds until `status` is `succeeded` or `failed`.
3. Read the transcript from `result`, with speaker labels and segment-level timestamps.

Once a transcription has succeeded, you can derive a summary or a tag set from it the same way: `POST /v1/summarize` or `POST /v1/tag`, then poll the job it returns. See [Summarise or Tag the Transcript](service/walkthrough.md#6-summarise-or-tag-the-transcript) in the Walkthrough.

For every endpoint's full request/response detail, see the [API Reference](service/api-reference.md).

## Need more?

For higher volume, or a regulated-sector or APAC-language use case, reach out to the team via [contact@makimoto.ai](mailto:contact@makimoto.ai) and we will help size a plan.
