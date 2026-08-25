# Getting Started

This page gets you from no account to a finished transcript.

## 1. Create an account

Create an account at [makimoto.ai](https://makimoto.ai). Every account includes a free monthly allowance of 1,000 minutes.

## 2. Generate an API token

Generate an API token from the developer/API section of the dashboard. See [Service → Authentication](service/authentication.md) for how tokens work and how long they last.

## 3. Try it

Two ways to make your first call:

- **In your browser**, with the [playground](https://github.com/makimoto-ai/kawa/tree/main/demo): pick a sample recording, submit it, and read the transcript, with the exact `curl` shown for every call.

- **In code**, with the [`quickstart.py`](https://github.com/makimoto-ai/kawa/blob/main/demo/quickstart.py) script or the [`KawaClient`](https://github.com/makimoto-ai/kawa/blob/main/demo/kawa_client.py) reference client, a small, fully typed client that depends only on `requests`.

## 4. Submit, poll, and read a transcript

The full request and response flow, including supported audio formats and size limits, is in [Service → Authentication and quickstart](service/authentication.md).

In short:

1. `POST /v1/transcriptions` with the audio file, to get a `job_id`.
2. `GET /v1/transcriptions/{job_id}` every few seconds until `status` is `succeeded` or `failed`.
3. Read the transcript from `result`, with speaker labels and segment-level timestamps.

## Need more?

For higher volume, a regulated-sector use case, or an Asia-Pacific language not yet supported, reach out to the team via [contact@makimoto.ai](mailto:contact@makimoto.ai).
