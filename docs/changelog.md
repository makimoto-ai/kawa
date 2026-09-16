# Changelog

*Last updated: 2026-09-16*

*Notable changes to Kawa, most recent first.* 

For more info, (see the [FAQ](faq.md) and [ROADMAP.md](https://github.com/makimoto-ai/kawa/blob/main/ROADMAP.md) for where things are headed). 

For the Python SDK's own release history, see its [CHANGELOG.md](https://github.com/makimoto-ai/makimoto-python/blob/main/CHANGELOG.md).

## 2026-09-16 - Mako Release

- New `POST /v1/summarize` and `POST /v1/tag` endpoints derive a summary or a fixed-taxonomy tag set from a succeeded transcription; see the [API Reference](service/api-reference.md#post-v1summarize).
- `GET /v1/transcriptions/{job_id}` now returns `type` (`transcription`, `summary`, or `tags`) and, for a postprocessing job, `source_job_id`.
- `KawaClient` (`demo/kawa_client.py`) gained `create_summary()` and `create_tags()`, plus the `SummaryResult` and `TagsResult` accessors on `Job`; see [Using `KawaClient`](https://github.com/makimoto-ai/kawa/blob/main/demo/README.md#summarise-or-tag-a-transcription).
- The Gradio playground was updated to reflect the above API changes. 

## 2026-07-01 — Launch

- Post-conversation transcription API, hosted in Singapore
- Open-source interactive playground and Python reference client (`demo/`)
- Orchestration layer published under the MIT licence
- Developer portal and API documentation at makimoto.ai
