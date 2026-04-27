# Kawa
 
> A composable transcription pipeline for conversational AI in Asia-Pacific.
 
[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue.svg)](LICENSE)
[![Status: Pre-launch](https://img.shields.io/badge/Status-Pre--launch-yellow.svg)](#status)
[![Discord](https://img.shields.io/badge/Discord-Join-7289DA.svg)](https://discord.gg/INVITE_CODE)
 
## Status
 
Kawa is in pre-launch. The first release ships **1 July 2026**.
 
On launch day:
- Two managed APIs (real-time and post-call), hosted in Singapore
- The orchestration layer published in this repository under the MIT licence
- A waitlist-driven early-access programme for developers
 
Source code is not yet published in this repository. Internal pipeline components (voice activity detection, diarisation, noise filtering, speech-to-text inference, post-processing) will open progressively through 2026 and 2027. We will not introduce source-available carve-outs or Business Source License terms; the orchestration layer is and will remain MIT-licensed.
 
## What is Kawa?
 
Kawa is a transcription pipeline with two managed APIs at launch: one for real-time use cases like live captioning and voice agents, one for post-call workloads like recorded calls and batch analytics. Both APIs run the same five-stage pipeline:
 
1. Audio resampling
2. Voice activity detection with speaker diarisation
3. Noise filtering and audio enhancement
4. Speech-to-text inference
5. Post-processing for normalisation, temporal ordering, speaker labelling, and structured output
 
Each stage is replaceable. Tune for your language, your domain, or your latency budget.
 
## Why Kawa?
 
- **A pipeline you can read.** The orchestration layer is MIT-licensed and published here. Read the source, file issues, fork it, contribute back.
- **Your data stays where you deploy.** Customer audio and transcripts are processed in country, not just stored there. Singapore at launch, with country-specific deployments to follow.
- **Modular by design.** Composability is the architecture, not a feature. Every stage can be swapped or tuned.
 
## Get early access
 
Join the waitlist at [makimoto.ai](https://makimoto.ai). We are onboarding developers in order of registration ahead of the 1 July launch, and prioritising open-source projects, regulated-sector applications, and APAC-language tooling.
 
## Roadmap
 
See [ROADMAP.md](ROADMAP.md) for the published roadmap.
 
## Contributing
 
Contributions, issues, and feature requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved.
 
## Community
 
- **Email**: hello@makimoto.ai
- **Issues**: Use [GitHub Issues](https://github.com/makimoto-ai/kawa/issues) for bugs and feature requests
- **Security**: For security issues, see [SECURITY.md](SECURITY.md)
- **Discord**: _Coming soon_
 
## Licence
 
The Kawa orchestration layer is published under the [MIT Licence](LICENSE). Internal pipeline components, when opened, will be published under MIT or another OSI-approved permissive licence.
 
## About
 
Kawa is part of [Makimoto](https://makimoto.ai), an open-source initiative by [Toku](https://toku.co).
