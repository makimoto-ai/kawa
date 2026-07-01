# Makimoto Kawa — Transcription playground

An open-source [Gradio](https://www.gradio.app) playground for the Makimoto Kawa
transcription API, and the sample app for integrating it: connect a token,
submit a recording, watch it transcribe, and read the result, with the exact
`curl` for every call shown alongside.

<img width="1158" height="766" alt="image" src="https://github.com/user-attachments/assets/733a7b02-6272-4966-8593-143504cc9841" />



It is built on a small reference client, [`kawa_client.py`](kawa_client.py),
documented under [Using `KawaClient`](#using-kawaclient) below. For the same flow
with no UI, see [`quickstart.py`](quickstart.py) and [QUICKSTART.md](QUICKSTART.md).

## Run

Requires Python 3.10 or newer.

```bash
cd demo
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install --upgrade -r requirements.txt
python app.py
```

Open the local URL it prints. By default the app finds a free port; set
`GRADIO_SERVER_PORT` to pin one, or `GRADIO_SERVER_NAME=0.0.0.0` to bind all
interfaces. Then add a token in the **Connection** panel (or preload it with
`MAKIMOTO_API_TOKEN`, see [Configuration](#configuration)) and submit a sample.

## What it does

The playground follows the one flow the API is built around, across two tabs:

**Transcribe**
- Pick a bundled sample from the sample folder, or add a recording from your
  device with "Add from device" (it is copied into the sample folder so it stays
  available next time).
- See a waveform of the audio before you send it.
- Submit it (`POST /v1/transcriptions`) and watch the job poll to completion.
- Read the result as a speaker-separated, timestamped conversation.

**Your transcriptions**
- List every job on your account (`GET /v1/transcriptions`).
- Open any one (`GET /v1/transcriptions/{job_id}`) and read it the same way.
- Delete a job (`DELETE /v1/transcriptions/{job_id}`) where the deployment
  supports cleanup.

Every action shows the exact `curl` equivalent with a copy button, and the raw
JSON response is one accordion away. The token is referenced as
`$MAKIMOTO_API_TOKEN` in the snippets, never inlined.

## Configuration

```bash
export MAKIMOTO_API_URL="https://api.makimoto.ai"   # production default
export MAKIMOTO_API_TOKEN="<token-from-dashboard>"  # preloads the token field
export MAKIMOTO_SAMPLE_DIR="../samples-audio"        # optional sample override
```

The token is held only in the local browser session; it is never written to
this repository. You can also paste it into the **Connection** panel at runtime.

## Using `KawaClient`

[`kawa_client.py`](kawa_client.py) is the file to copy into your project. It
depends only on `requests`, is fully typed, and maps one method to each endpoint:

```
GET    /v1/transcriptions            -> list jobs
POST   /v1/transcriptions            -> submit audio (multipart), returns job_id
GET    /v1/transcriptions/{job_id}   -> job status + transcript when succeeded
DELETE /v1/transcriptions/{job_id}   -> remove a job (where supported)
```

Construct it with a token and (optionally) a base URL:

```python
from kawa_client import KawaClient

client = KawaClient(token="<dashboard-token>")
# or point at a non-production deployment:
# client = KawaClient(token="<token>", api_url="https://api.eu.makimoto.ai")
```

### Submit a recording and read the transcript

`create_transcription` uploads the file as multipart form-data and returns a
`Job` immediately, before transcription finishes. `poll` then yields the job on
each check until it reaches a terminal status, so you can drive a progress
indicator; the last value it yields is the finished job.

```python
job = client.create_transcription("call.mp3", language="en")

final = None
for update in client.poll(job.job_id):
    print(update.status)          # queued -> processing -> succeeded
    final = update

if final.status == "succeeded":
    print(final.result.full_text)
    for seg in final.result.segments:
        print(f"[{seg.speaker_alias}] {seg.text}")
```

`language` is optional (auto-detected when omitted), and you can attach an
arbitrary JSON object that is stored alongside the job:

```python
job = client.create_transcription(
    "call.mp3",
    language="en",
    metadata={"source": "support-line", "ticket": 4821},
)
```

If you would rather block until done than stream updates, exhaust the iterator:

```python
*_, final = client.poll(job.job_id, interval=2.0, max_attempts=60)
```

### List, fetch, and delete jobs

```python
for job in client.list_transcriptions():
    print(job.job_id, job.status)

job = client.get_transcription("00000000-0000-0000-0000-000000000000")
if job.result:
    print(job.result.language, job.result.words_count)

client.delete_transcription(job.job_id)   # where the deployment supports it
```

### What you get back

A `Job` carries the raw response plus typed accessors. Once it succeeds,
`job.result` is a `TranscriptResult` and `job.result.segments` is a list of
speaker-attributed `Segment`s:

```python
@dataclass(frozen=True)
class Segment:
    text: str
    time_start: float
    time_end: float
    speaker_id: int
    speaker_alias: str

@dataclass(frozen=True)
class TranscriptResult:
    language: Optional[str]
    duration_seconds: Optional[float]
    words_count: Optional[int]
    segments: List[Segment]

    @property
    def full_text(self) -> str: ...
```

`job.is_terminal` is true once the status is `succeeded` or `failed`, and
`job.error` holds the error payload on failure.

### Handling errors

Any non-2xx response raises `KawaError`, which keeps the status code and parsed
body so you can branch on the failure:

```python
from kawa_client import KawaError

try:
    job = client.get_transcription(job_id)
except KawaError as exc:
    if exc.status_code == 401:
        ...   # token missing, expired, or revoked
    elif exc.status_code == 404:
        ...   # unknown job
    else:
        raise
```

## Authentication

Authenticate every request with a token generated from the Makimoto dashboard:

```http
Authorization: Bearer <makimoto_api_token>
```

There is no client-side refresh. If the dashboard issues an opaque key, rotate
it in the dashboard. If it issues a short-lived JWT, copy a fresh one when it
expires — the Connection panel decodes and shows JWT expiry locally so you can
spot a stale token. A `401` from the API means the token is missing, expired,
or revoked.

See [../docs/api-authentication-quickstart.md](../docs/api-authentication-quickstart.md)
for the full HTTP contract.

## Sample audio

The bundled recordings in [`../samples-audio`](../samples-audio) are third-party
test files, used here under their respective terms:

- **`harvard.wav`, `jackhammer.wav`** — Harvard sentences read by a single
  speaker (clean, and with background noise), from the
  [Open Speech Repository](https://www.voiptroubleshooter.com/open_speech/)
  (Telchemy), via the
  [Real Python speech-recognition examples](https://github.com/realpython/python-speech-recognition/tree/master/audio_files).
  Freely usable, with attribution to the Open Speech Repository.

**CallHome**, the well-known conversational-telephone diarisation benchmark, is
licensed through the [Linguistic Data Consortium](https://www.ldc.upenn.edu/)
and is not redistributable, so it is not bundled here. If you hold an LDC
licence, point the playground or `quickstart.py` at your own copy.

See [../samples-audio/ATTRIBUTION.md](../samples-audio/ATTRIBUTION.md) for full
provenance and terms.
