# 🌊 Kawa

> Open-source, Singapore-hosted transcription for conversational AI in Asia-Pacific.

[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue.svg)](LICENSE)
[![Status: Live](https://img.shields.io/badge/Status-Live-brightgreen.svg)](https://makimoto.ai)
[![API docs](https://img.shields.io/badge/API-docs-6200EB.svg)](docs/api-authentication-quickstart.md)
[![Made in Singapore](https://img.shields.io/badge/Made%20in-Singapore-red.svg)](#-data-residency-and-sovereignty)

**Kawa is live.** Makimoto Kawa is the first open-source conversational AI infrastructure built and hosted in Singapore, for teams working under APAC data-residency and regulatory requirements. The post-conversation transcription API and an interactive playground are available now.

**Quick links:** [Get an account](https://makimoto.ai) · [Playground](demo) · [Quickstart](demo/QUICKSTART.md) · [API docs](docs/api-authentication-quickstart.md) · [Roadmap](ROADMAP.md)

## 🚀 Get started

1. **Create an account** at [makimoto.ai](https://makimoto.ai). Every account includes a **free monthly allowance of 1,000 minutes**.
2. **Generate an API token** from the dashboard.
3. **Try it**, two ways:
   - 🖥️ **In your browser** with the [playground](demo): pick a sample, submit, read the transcript.
   - 🐍 **In code** with the [`quickstart.py`](demo/quickstart.py) script or the [`KawaClient`](demo/kawa_client.py) reference client.

Need more minutes, or have a regulated-sector or APAC-language use case? Email [contact@makimoto.ai](mailto:contact@makimoto.ai) and we will help size a plan.

## 🎛️ Playground and reference client

<img width="1158" height="766" alt="image" src="https://github.com/user-attachments/assets/ff99d002-d987-4193-9aaa-2b661d4452fd" />

The [`demo/`](demo) directory is the sample app for the transcription API:

| File | What it is |
| --- | --- |
| [`app.py`](demo/app.py) | **Playground** — a [Gradio](https://www.gradio.app) UI that submits audio and shows the transcript, with the exact `curl` for every call. |
| [`kawa_client.py`](demo/kawa_client.py) | **Reference client** — a small, fully typed `KawaClient` that depends only on `requests`. Copy it into your project. |
| [`quickstart.py`](demo/quickstart.py) | **Quickstart** — a no-UI script that transcribes a file end to end. |

Run instructions in [demo/README.md](demo/README.md), the [`KawaClient` reference](demo/README.md#using-kawaclient), and a no-UI walkthrough in [demo/QUICKSTART.md](demo/QUICKSTART.md). Bundled test audio lives in [`samples-audio/`](samples-audio) ([attribution](samples-audio/ATTRIBUTION.md)).

## 📡 The API

Submit a recording, poll the job, then read the transcript with speaker separation and segment-level timestamps.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/v1/transcriptions` | Submit audio (multipart); returns a job id |
| `GET` | `/v1/transcriptions` | List your jobs |
| `GET` | `/v1/transcriptions/{job_id}` | Job status, and the transcript once done |
| `DELETE` | `/v1/transcriptions/{job_id}` | Remove a job (where supported) |

Authenticate every request with `Authorization: Bearer <token>`. Full HTTP contract in [docs/api-authentication-quickstart.md](docs/api-authentication-quickstart.md); OpenAPI spec in [docs/openapi.json](docs/openapi.json).

## 🧩 How it works

Kawa is a composable transcription pipeline. The first managed API, available now, handles post-conversation workloads: recorded calls, voicemail, and large-scale analysis of archived customer interactions. A real-time API for live captioning, voice agents, and in-conversation analytics will follow.

Both run the same five stages, each replaceable so you can tune for your language, domain, or latency budget:

1. Audio resampling
2. Voice activity detection with speaker diarisation
3. Noise filtering and audio enhancement
4. Speech-to-text inference
5. Post-processing (normalisation, temporal ordering, speaker labelling, structured output)

## 🔒 Data residency and sovereignty

Hosted in Singapore, Kawa keeps customer audio and transcripts in-country, supporting organisations under Singapore's Personal Data Protection Act (PDPA) and sector frameworks including Monetary Authority of Singapore (MAS) guidelines. The architecture established for Singapore is the foundation for future deployments in markets with similar data-residency and compliance requirements.

## 🗺️ Roadmap

- **H2 2026:** real-time transcription API, a self-hostable pipeline, and more Asia-Pacific jurisdictions.
- **2027:** progressive opening of all internal pipeline components.

Full detail in [ROADMAP.md](ROADMAP.md). We will not introduce source-available carve-outs or Business Source License terms; the orchestration layer is and will remain MIT-licensed.

## 🤝 Contributing

Issues and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). All participants follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## 💬 Community

- 📧 **Email:** contact@makimoto.ai
- 🐛 **Issues:** [GitHub Issues](https://github.com/makimoto-ai/kawa/issues) for bugs and feature requests
- 🔒 **Security:** see [SECURITY.md](SECURITY.md); please do not open public issues for vulnerabilities
- 💬 **Discord:** _coming soon_

## 📄 Licence

Released under the [MIT Licence](LICENSE). Internal pipeline components, when opened, will be published under MIT or another OSI-approved permissive licence.

---

Kawa is developed in the open as part of [Makimoto](https://makimoto.ai), operated by Makimoto Technology Pte Ltd, a wholly-owned subsidiary of the [Toku](https://toku.co) Group.
