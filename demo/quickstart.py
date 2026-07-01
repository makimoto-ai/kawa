"""Minimal end-to-end example of the Makimoto Kawa transcription API.

No Gradio, no UI: construct the client, submit a recording, poll until done,
then print the transcript. This is the shortest path from a token to text.

    export MAKIMOTO_API_TOKEN="<token-from-dashboard>"
    python quickstart.py                       # uses a bundled sample
    python quickstart.py /path/to/audio.mp3    # or your own recording
"""

from __future__ import annotations

import os
import sys

from kawa_client import KawaClient, KawaError

DEFAULT_AUDIO = "../samples-audio/jackhammer.wav"


def main() -> int:
    token = os.getenv("MAKIMOTO_API_TOKEN", "").strip()
    if not token:
        print("Set MAKIMOTO_API_TOKEN to a token from the Makimoto dashboard.")
        return 1

    audio = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AUDIO
    api_url = os.getenv("MAKIMOTO_API_URL", "https://api.makimoto.ai")
    client = KawaClient(token=token, api_url=api_url)

    try:
        job = client.create_transcription(audio, language="en")
        print(f"Submitted {audio}  ->  job {job.job_id}")

        final = None
        for update in client.poll(job.job_id):
            print(f"  status: {update.status}")
            final = update
    except KawaError as exc:
        print(f"API error {exc.status_code}: {exc}")
        return 1

    if not (final and final.status == "succeeded" and final.result):
        print(f"Job did not succeed (status: {final.status if final else 'unknown'}).")
        return 1

    result = final.result
    print(f"\nLanguage: {result.language}   Words: {result.words_count}\n")
    for seg in result.segments:
        print(f"[{seg.speaker_alias}] {seg.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
