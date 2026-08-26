# How It Works

Kawa is a composable transcription pipeline. The first managed API, available now, handles post-conversation workloads: recorded calls, voicemail, and large-scale analysis of archived customer interactions. 

A real-time API for live captioning, voice agents, and in-conversation analytics is planned; see the [roadmap](https://github.com/makimoto-ai/kawa/blob/main/ROADMAP.md).

Both run the same five stages, each replaceable so you can tune for your language, domain, or latency budget.

## The five stages

1. Audio resampling
2. Voice activity detection with speaker diarisation
3. Noise filtering and audio enhancement
4. Speech-to-text inference
5. Post-processing (normalisation, temporal ordering, speaker labelling, structured output)

## Terms used in this documentation

| Term | Meaning |
| --- | --- |
| Job | One submitted audio file, tracked through `queued`, `processing`, `succeeded`, or `failed`. |
| Segment | One span of transcript text attributed to a single speaker, with start and end timestamps. |
| Speaker alias | A per-job label (`Speaker 0`, `Speaker 1`, ...) assigned by diarisation. |
| Post-conversation | Transcription of a recording after the conversation has ended, as opposed to real-time, in-call transcription. |

## Data Residency

Kawa is hosted in Singapore and keeps customer audio and transcripts in-country, supporting organisations under Singapore's Personal Data Protection Act (PDPA) and sector frameworks including Monetary Authority of Singapore (MAS) guidelines.
