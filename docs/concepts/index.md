# How It Works

*Last updated: 2026-09-16*

Kawa is a composable transcription pipeline. The first managed API, available now, handles post-conversation workloads: recorded calls, voicemail, and large-scale analysis of archived customer interactions. 

A real-time API for live captioning, voice agents, and in-conversation analytics is planned; see the [roadmap](https://github.com/makimoto-ai/kawa/blob/main/ROADMAP.md).

Both run the same five stages, each replaceable so you can tune for your language, domain, or latency budget.

## The five stages

1. Audio resampling
2. Voice activity detection with speaker diarisation
3. Noise filtering and audio enhancement
4. Speech-to-text inference
5. Post-processing (normalisation, temporal ordering, speaker labelling, structured output)

## Summaries and Tags

Once a transcription job has `succeeded`, it can be sent through two further, on-demand steps: summarisation, which produces a topic and prose summary, and tagging, which classifies the conversation against a fixed taxonomy (call reason, customer sentiment, and so on). Each is a separate job in its own right, created from an existing transcription via [`POST /v1/summarize`](../service/api-reference.md#post-v1summarize) or [`POST /v1/tag`](../service/api-reference.md#post-v1tag), and polled the same way. Unlike the five pipeline stages above, these are opt-in per transcription rather than run on every upload.

Either endpoint also accepts plain text directly (`transcript_text`), bypassing transcription and the audio pipeline entirely.

## Terms used in this documentation

| Term | Meaning |
| --- | --- |
| Job | One submitted audio file, or one summary/tag request, tracked through `queued`, `processing`, `succeeded`, or `failed`. |
| Segment | One span of transcript text attributed to a single speaker, with start and end timestamps. |
| Speaker alias | A per-job label (`User`, `Agent`) assigned by diarisation. |
| Post-conversation | Transcription of a recording after the conversation has ended, as opposed to real-time, in-call transcription. |
| Job type | `transcription`, `summary`, or `tags` — which of the three result shapes a job's `result` carries. |

## Data Residency

Kawa is hosted in Singapore and keeps customer audio and transcripts in-country, supporting organisations under Singapore's Personal Data Protection Act (PDPA) and sector frameworks including Monetary Authority of Singapore (MAS) guidelines.
