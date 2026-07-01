# Sample audio attribution

Third-party test files in this directory and their provenance. Files originating
from Toku's own platform (for example the `06b07229-…` call recordings) are not
listed here.

## jackhammer.wav, harvard.wav

- Source: Open Speech Repository (developed by Telchemy), via the Real Python
  `python-speech-recognition` examples.
  - https://www.voiptroubleshooter.com/open_speech/
  - https://github.com/realpython/python-speech-recognition/tree/master/audio_files
- Content: Harvard sentences read by a single speaker. `jackhammer.wav` is the
  same style of speech with a loud jackhammer in the background; `harvard.wav` is
  clean. They form a clean-versus-noisy pair for testing transcription under
  noise.
- Terms: freely usable, with the requirement to identify the source as the
  "Open Speech Repository".

## Related datasets (not bundled)

- **CallHome** — a standard conversational-telephone-speech and speaker-diarisation
  benchmark. It is licensed through the Linguistic Data Consortium and is **not
  redistributable**, so it is referenced here rather than shipped. Bring your own
  copy if you hold an LDC licence.
  - https://www.ldc.upenn.edu/ (search the CallHome / CALLHOME corpora)
