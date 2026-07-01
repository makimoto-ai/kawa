# Quickstart — transcribe without the UI

[`quickstart.py`](quickstart.py) is the shortest path from an API token to text:
~40 lines, no Gradio, no browser. It uses the same
[`kawa_client.py`](kawa_client.py) reference client as the playground to submit a
recording, poll until done, and print the transcript.

## Run

Requires Python 3.10 or newer and `requests` (installing
[requirements.txt](requirements.txt) covers it, or just `pip install requests`).

```bash
cd demo
export MAKIMOTO_API_TOKEN="<token-from-dashboard>"
python quickstart.py                       # uses a bundled sample (jackhammer.wav)
python quickstart.py /path/to/audio.mp3    # or your own recording
```

Optionally point it at a non-production deployment:

```bash
export MAKIMOTO_API_URL="https://api.makimoto.ai"   # production default
```

## What you'll see

```
Submitted ../samples-audio/jackhammer.wav  ->  job 0c4f...
  status: queued
  status: processing
  status: succeeded

Language: en   Words: 27

[Speaker 0] The stale smell of old beer lingers.
...
```

A non-zero exit code means it stopped early: no token set, an API error (the
status code and message are printed), or a job that did not reach `succeeded`.

## Next step

To build this into your own project, copy [`kawa_client.py`](kawa_client.py) and
see the [`KawaClient` reference](README.md#using-kawaclient) for the full client
API: optional `language` and `metadata`, listing and deleting jobs, the returned
`Job` / `TranscriptResult` / `Segment` shapes, and error handling.
