"""Makimoto Kawa - Transcription API playground.

A Gradio UI over the Makimoto transcription API: connect a token, submit a
recording and watch it poll to completion, then read the transcript as the
conversation it came from.

The API calls go through ``KawaClient`` from ``kawa_client.py``, a small,
dependency-light reference client (only ``requests``) that you can copy
straight into your own project. See ``quickstart.py`` for the same flow without
any UI.

Run it:

    cd demo
    python3 -m venv .venv && source .venv/bin/activate
    pip install --upgrade -r requirements.txt
    python app.py

Then open the local URL it prints (default http://127.0.0.1:8800).

The API contract used here:

    GET    /v1/transcriptions            -> list jobs
    POST   /v1/transcriptions            -> submit audio (multipart), returns job_id
    GET    /v1/transcriptions/{job_id}   -> job status + transcript when succeeded
    DELETE /v1/transcriptions/{job_id}   -> remove a job (where supported)

Authenticate every request with a dashboard token:

    Authorization: Bearer <makimoto_api_token>
"""

from __future__ import annotations

import base64
import html
import json
import os
import shutil
import wave
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import gradio as gr
import numpy as np
import requests

# The reference client lives in its own dependency-light module so it can be
# copied into a project without any of the Gradio playground below.
from kawa_client import (
    DEFAULT_API_URL,
    Job,
    KawaClient,
    KawaError,
    TranscriptResult,
)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_DIR = ROOT_DIR / "samples-audio"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}

# Environment defaults. The token is read once for convenience when developing
# locally; the UI keeps whatever you type only in the local browser session.
ENV_API_URL = os.getenv("MAKIMOTO_API_URL", DEFAULT_API_URL).rstrip("/")
ENV_TOKEN = os.getenv("MAKIMOTO_API_TOKEN", "")
ENV_SAMPLE_DIR = Path(os.getenv("MAKIMOTO_SAMPLE_DIR", str(DEFAULT_SAMPLE_DIR))).expanduser()


# --------------------------------------------------------------------------- #
# curl builders  (documentation that doubles as copy-paste shell commands)
# --------------------------------------------------------------------------- #
#
# The token is never written into these snippets; they reference the
# $MAKIMOTO_API_TOKEN environment variable so a copied command stays safe to
# paste into a terminal or commit to a script.


def _shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def curl_list(api_url: str) -> str:
    return (
        "curl -sS \\\n"
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions')} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_TOKEN"'
    )


def curl_create(api_url: str, file_path: str, language: str, metadata: str) -> str:
    lines = [
        "curl -sS -X POST \\",
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions')} \\",
        '  -H "Authorization: Bearer $MAKIMOTO_API_TOKEN" \\',
        f"  -F {_shell_quote('file=@' + (file_path or '/path/to/audio.mp3'))} \\",
    ]
    if (language or "").strip():
        lines.append(f"  -F {_shell_quote('language=' + language.strip())} \\")
    compact = _compact_metadata(metadata)
    if compact and compact != "{}":
        lines.append(f"  -F {_shell_quote('metadata=' + compact)}")
    else:
        # drop the trailing backslash from the last meaningful line
        lines[-1] = lines[-1].rstrip(" \\")
    return "\n".join(lines)


def curl_get(api_url: str, job_id: str) -> str:
    return (
        "curl -sS \\\n"
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions/' + (job_id or '<job_id>'))} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_TOKEN"'
    )


def curl_delete(api_url: str, job_id: str) -> str:
    return (
        "curl -sS -X DELETE \\\n"
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions/' + (job_id or '<job_id>'))} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_TOKEN"'
    )


# --------------------------------------------------------------------------- #
# Small shared utilities
# --------------------------------------------------------------------------- #


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _compact_metadata(raw: str) -> str:
    """Validate metadata JSON and return it minified, or '{}' when blank."""
    if not raw or not raw.strip():
        return "{}"
    parsed = json.loads(raw)  # raises on bad JSON; surfaced to the user
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return json.dumps(parsed, separators=(",", ":"))


def _parse_metadata(raw: str) -> Dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return parsed


def _fmt_clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def response_dump(status: Optional[int], headers: Dict[str, str], body: Any) -> str:
    """A full response dump for the raw panel: status, headers, and parsed body.

    Showing the status and headers (not just the body) is what makes the panel
    useful for debugging: a 413 reveals its ``Server`` header, a 429 its
    ``Retry-After``, and so on.
    """
    return _pretty_json({"status": status, "headers": dict(headers or {}), "body": body})


def error_dump(exc: Exception) -> str:
    """Render an exception for the raw panel.

    ``KawaError`` carries the HTTP status, headers and body from the failed
    response; anything else (a timeout, DNS failure) has no response to show.
    """
    if isinstance(exc, KawaError):
        return response_dump(exc.status_code, exc.headers, exc.body)
    return _pretty_json({"error": f"{type(exc).__name__}: {exc}"})


# --------------------------------------------------------------------------- #
# Sample + audio resolution
# --------------------------------------------------------------------------- #


def list_samples(sample_dir: str | Path = ENV_SAMPLE_DIR) -> List[str]:
    directory = Path(sample_dir).expanduser()
    if not directory.exists():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def sample_path(name: Optional[str], sample_dir: str | Path = ENV_SAMPLE_DIR) -> Optional[Path]:
    if not name:
        return None
    directory = Path(sample_dir).expanduser()
    path = directory / name
    try:  # guard against path traversal in the dropdown value
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return None
    return path if path.exists() else None


# --------------------------------------------------------------------------- #
# Brand + theme  (Makimoto: deep navy / violet #6200EB / cyan #00F6FF)
# --------------------------------------------------------------------------- #
#
# Brand colours sampled from makimoto.ai. The app ships both a dark theme (the
# brand default) and a light theme, switchable with the toggle in the masthead.

VIOLET = "#6200EB"   # primary accent (buttons, links)
VIOLET_HOVER = "#7A2BFF"
CYAN = "#00F6FF"     # secondary accent (gradients, glow)

# Status colours, with a variant per mode for legible contrast.
GOOD_D, BAD_D, PENDING_D = "#36D9A0", "#FF6B6B", "#FFC24B"
GOOD_L, BAD_L, PENDING_L = "#0F8A5A", "#C0392B", "#B7791F"

# The real Makimoto logo (the violet-to-cyan waveform glyph), inlined as a data
# URI so it renders without any path/allowlist concerns. Falls back to a small
# SVG recreation if the file is missing.
def _logo_data_uri() -> str:
    logo = Path(__file__).resolve().parent / "makimoto-logo.png"
    try:
        encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 26'>"
            "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
            f"<stop offset='0%' stop-color='{VIOLET}'/><stop offset='100%' stop-color='{CYAN}'/>"
            "</linearGradient></defs><g fill='url(%23g)'>"
            "<rect x='1' y='10' width='2.6' height='6' rx='1.3'/>"
            "<rect x='5' y='6' width='2.6' height='14' rx='1.3'/>"
            "<rect x='9' y='2' width='2.6' height='22' rx='1.3'/>"
            "<rect x='13' y='7' width='2.6' height='12' rx='1.3'/>"
            "<rect x='17' y='3' width='2.6' height='20' rx='1.3'/>"
            "<rect x='21' y='9' width='2.6' height='8' rx='1.3'/></g></svg>"
        )
        return "data:image/svg+xml;utf8," + svg


LOGO_URI = _logo_data_uri()
BRAND_MARK = f'<img class="mk-logo" src="{LOGO_URI}" alt="Makimoto" width="24" height="24" />'


def make_theme() -> gr.Theme:
    """Real light + dark themes. Gradio applies the ``_dark`` variants when the
    document carries the ``dark`` class, which the masthead toggle flips."""
    t = gr.themes.Base(
        primary_hue=gr.themes.colors.purple,
        secondary_hue=gr.themes.colors.cyan,
        neutral_hue=gr.themes.colors.slate,
        radius_size=gr.themes.sizes.radius_lg,
        font=["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
    )
    return t.set(
        # backgrounds
        body_background_fill="#F6F7FB",
        body_background_fill_dark="#010E39",
        background_fill_primary="#FFFFFF",
        background_fill_primary_dark="#0B1A47",
        background_fill_secondary="#F1F3FA",
        background_fill_secondary_dark="#081333",
        block_background_fill="#FFFFFF",
        block_background_fill_dark="#0B1A47",
        panel_background_fill="#FFFFFF",
        panel_background_fill_dark="#0B1A47",
        # borders
        block_border_color="rgba(1,14,57,0.12)",
        block_border_color_dark="rgba(255,255,255,0.10)",
        border_color_primary="rgba(1,14,57,0.12)",
        border_color_primary_dark="rgba(255,255,255,0.10)",
        # text
        body_text_color="#010E39",
        body_text_color_dark="#EEF2FF",
        body_text_color_subdued="#5B6485",
        body_text_color_subdued_dark="#8C99C6",
        block_label_text_color="#5B6485",
        block_label_text_color_dark="#8C99C6",
        block_title_text_color="#010E39",
        block_title_text_color_dark="#EEF2FF",
        # inputs
        input_background_fill="#F4F6FC",
        input_background_fill_dark="#050F33",
        input_border_color="rgba(1,14,57,0.14)",
        input_border_color_dark="rgba(255,255,255,0.10)",
        input_placeholder_color="#8B93AE",
        input_placeholder_color_dark="#6E7AA6",
        # accent + buttons
        color_accent=VIOLET,
        color_accent_soft="rgba(98,0,235,0.10)",
        color_accent_soft_dark="rgba(98,0,235,0.22)",
        button_primary_background_fill=VIOLET,
        button_primary_background_fill_dark=VIOLET,
        button_primary_background_fill_hover=VIOLET_HOVER,
        button_primary_background_fill_hover_dark=VIOLET_HOVER,
        button_primary_text_color="#FFFFFF",
        button_primary_text_color_dark="#FFFFFF",
        button_secondary_background_fill="transparent",
        button_secondary_background_fill_dark="transparent",
        button_secondary_text_color="#010E39",
        button_secondary_text_color_dark="#EEF2FF",
        button_secondary_border_color="rgba(1,14,57,0.16)",
        button_secondary_border_color_dark="rgba(255,255,255,0.14)",
    )


CSS = f"""
/* Palette: light is the default; .dark on <html> swaps to the brand navy.
   Every custom rule reads these vars, so the toggle restyles everything. */
:root {{
  --mk-bg: #F6F7FB;
  --mk-panel: #FFFFFF;
  --mk-well: #F1F3FA;
  --mk-ink: #010E39;
  --mk-muted: #5B6485;
  --mk-line: rgba(1,14,57,0.12);
  --mk-good: {GOOD_L};
  --mk-bad: {BAD_L};
  --mk-pending: {PENDING_L};
  --mk-code-ink: {VIOLET};
  --mk-violet: {VIOLET};
  --mk-cyan: {CYAN};
}}
.dark {{
  --mk-bg: #010E39;
  --mk-panel: #0B1A47;
  --mk-well: #050F33;
  --mk-ink: #EEF2FF;
  --mk-muted: #8C99C6;
  --mk-line: rgba(255,255,255,0.10);
  --mk-good: {GOOD_D};
  --mk-bad: {BAD_D};
  --mk-pending: {PENDING_D};
  --mk-code-ink: {CYAN};
}}

.gradio-container {{
  max-width: 1080px !important;
  margin: 0 auto !important;
  padding: 22px 20px 56px !important;
  background: var(--mk-bg) !important;
  color: var(--mk-ink) !important;
}}

/* Masthead ------------------------------------------------------------- */
.mk-mast {{ display: flex; align-items: center; gap: 9px; padding: 4px 2px 0; }}
.mk-logo {{ display: block; }}
.mk-word {{ font-size: 18px; font-weight: 650; letter-spacing: -0.01em; color: var(--mk-ink); }}
.mk-iconbtn {{ font-size: 16px !important; line-height: 1 !important; }}

.mk-title {{ font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin: 4px 0 2px; color: var(--mk-ink); }}
.mk-subtle {{ color: var(--mk-muted); font-size: 13.5px; }}
.mk-subtle b {{ color: var(--mk-ink); font-weight: 600; }}

/* Endpoint label ------------------------------------------------------- */
.mk-endpoint {{ display: flex; align-items: center; gap: 9px; margin: 2px 0 4px; font-size: 13px; }}
.mk-method {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 0.04em; padding: 2px 7px; border-radius: 5px;
}}
.mk-method.get {{ background: var(--mk-violet); color: #FFFFFF; }}
.mk-method.post {{ background: var(--mk-cyan); color: #010E39; }}
.mk-method.delete {{ background: var(--mk-bad); color: #FFFFFF; }}
.mk-endpoint code {{ font-size: 12.5px; color: var(--mk-ink); background: transparent; }}
.mk-hint {{ color: var(--mk-muted); font-size: 12.5px; margin: 2px 0 10px; }}
.mk-lede {{ font-size: 20px; font-weight: 650; letter-spacing: -0.01em; margin: 2px 0 4px; color: var(--mk-ink); }}
.mk-lede-sub {{ color: var(--mk-muted); font-size: 13.5px; max-width: 62ch; margin-bottom: 6px; }}

/* Status pill ---------------------------------------------------------- */
.mk-status {{ display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; padding: 2px 0; }}
.mk-dot {{ width: 8px; height: 8px; border-radius: 999px; background: var(--mk-muted); flex: 0 0 auto; }}
.mk-status.good .mk-dot {{ background: var(--mk-good); }}
.mk-status.bad .mk-dot {{ background: var(--mk-bad); }}
.mk-status.pending .mk-dot {{ background: var(--mk-pending); animation: mk-pulse 1.1s ease-in-out infinite; }}
.mk-status.good {{ color: var(--mk-good); }}
.mk-status.bad {{ color: var(--mk-bad); }}
.mk-status.pending {{ color: var(--mk-pending); }}
@keyframes mk-pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}

/* Waveform ------------------------------------------------------------- */
.mk-wave {{
  border: 1px solid var(--mk-line); border-radius: 12px; background: var(--mk-well);
  padding: 12px 14px; margin: 4px 0 2px;
}}
.mk-wave .mk-wave-top {{ display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px; }}
.mk-wave .mk-name {{ font-weight: 600; font-size: 13px; color: var(--mk-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.mk-wave .mk-meta {{ color: var(--mk-muted); font-size: 12px; white-space: nowrap; }}
.mk-wave svg {{ display: block; width: 100%; height: 58px; }}
.mk-wave.empty {{ color: var(--mk-muted); font-size: 13px; text-align: center; padding: 26px; }}

/* Transcript metrics --------------------------------------------------- */
.mk-metrics {{ display: flex; flex-wrap: wrap; gap: 22px; padding: 4px 2px 2px; }}
.mk-metrics div {{ display: flex; flex-direction: column; gap: 1px; }}
.mk-metrics small {{ color: var(--mk-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }}
.mk-metrics strong {{ font-size: 15px; font-weight: 600; color: var(--mk-ink); }}

.mk-fail {{
  border: 1px solid var(--mk-line); border-left: 3px solid var(--mk-bad); border-radius: 10px;
  padding: 12px 14px; background: var(--mk-panel);
}}
.mk-fail strong {{ color: var(--mk-bad); display: block; font-size: 13px; }}
.mk-fail small {{ color: var(--mk-muted); }}

.mk-empty {{ color: var(--mk-muted); font-size: 13px; padding: 8px 2px; }}

/* Inline code inside markdown/hints (the gr.Code editors are untouched) */
.gradio-container p code,
.gradio-container li code,
.gradio-container .mk-hint code {{
  background: var(--mk-well) !important;
  color: var(--mk-code-ink) !important;
  border: 1px solid var(--mk-line);
  padding: 1px 6px; border-radius: 6px; font-size: 0.9em;
}}

/* Responsive: keep it simple - tighten spacing and scale headings down */
@media (max-width: 760px) {{
  .gradio-container {{ padding: 16px 12px 40px !important; }}
  .mk-title {{ font-size: 22px; }}
  .mk-metrics {{ gap: 16px; }}
}}

footer {{ display: none !important; }}
"""

# Apply the saved theme (brand default: dark) before first paint, so there is
# no flash of the wrong palette.
HEAD = """
<script>
(function () {
    function syncTheme(isDark) {
        document.documentElement.classList.toggle('dark', isDark);
        if (document.body) document.body.classList.toggle('dark', isDark);
    }
    var isDark = true;
  try {
    var pref = localStorage.getItem('mk-theme') || 'dark';
        isDark = pref !== 'light';
    } catch (e) {
        isDark = true;
    }
    // Keep html and body in sync so first toggle after refresh does not drift.
    syncTheme(isDark);
    if (!document.body) {
        document.addEventListener('DOMContentLoaded', function () { syncTheme(isDark); }, { once: true });
    }
})();
</script>
"""

# Masthead toggle: flip the .dark class on <html>, persist the choice, no reload.
THEME_TOGGLE_JS = """
() => {
    var isDark = document.documentElement.classList.contains('dark') || (document.body && document.body.classList.contains('dark'));
    document.documentElement.classList.toggle('dark', !isDark);
    if (document.body) document.body.classList.toggle('dark', !isDark);
    try { localStorage.setItem('mk-theme', !isDark ? 'dark' : 'light'); } catch (e) {}
}
"""


# --------------------------------------------------------------------------- #
# View helpers  (turn API data into the UI)
# --------------------------------------------------------------------------- #


def status_pill(text: str, kind: str = "") -> str:
    return f'<div class="mk-status {kind}"><span class="mk-dot"></span><span>{_esc(text)}</span></div>'


def _decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    token = (token or "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None


def signed_in_html(token: str) -> str:
    """The 'Connected as …' line shown under the masthead."""
    token = (token or "").strip()
    if not token:
        return '<div class="mk-subtle">Not connected. Add a token under Connection to begin.</div>'
    payload = _decode_jwt(token)
    if payload:
        who = payload.get("email") or payload.get("username") or payload.get("sub") or "your account"
        return f'<div class="mk-subtle">Connected as <b>{_esc(who)}</b></div>'
    return '<div class="mk-subtle">Connected with an API key</div>'


def status_for(job: Job) -> str:
    mapping = {"succeeded": "good", "failed": "bad", "queued": "pending", "processing": "pending"}
    return mapping.get(job.status, "")


def _envelope(path: Path, buckets: int = 200) -> np.ndarray:
    """Return a [0,1] amplitude envelope for the waveform.

    WAV files are decoded to real PCM peaks. Other formats fall back to a
    byte-energy estimate, which is enough for a recognisable visual.
    """
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as w:
                frames = w.readframes(w.getnframes())
                width = w.getsampwidth()
            dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width, np.int16)
            samples = np.frombuffer(frames, dtype=dtype).astype(np.float32)
            if dtype == np.uint8:
                samples -= 128.0
        else:
            raw = np.frombuffer(path.read_bytes(), dtype=np.uint8).astype(np.float32)
            samples = np.abs(raw - 128.0)
    except Exception:
        return np.zeros(buckets)
    if samples.size == 0:
        return np.zeros(buckets)
    chunks = np.array_split(np.abs(samples), min(buckets, samples.size))
    env = np.array([float(np.sqrt(np.mean(c ** 2))) if c.size else 0.0 for c in chunks])
    peak = float(env.max()) or 1.0
    return env / peak


def waveform_html(path: Optional[Path]) -> str:
    if not path or not path.exists():
        return '<div class="mk-wave empty">No audio selected. Choose a sample or upload a recording.</div>'
    env = _envelope(path)
    width, height, mid = 1000.0, 100.0, 50.0
    step = width / max(1, len(env))
    bar_w = max(1.4, step * 0.62)
    bars = []
    for i, v in enumerate(env):
        h = max(2.0, v * 92.0)
        x = i * step + (step - bar_w) / 2
        bars.append(f'<rect x="{x:.1f}" y="{mid - h / 2:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="{bar_w / 2:.1f}"/>')
    size = _human_size(path.stat().st_size)
    fmt = (path.suffix.lstrip(".") or "audio").upper()
    return f"""
    <div class="mk-wave">
      <div class="mk-wave-top">
        <span class="mk-name">{_esc(path.name)}</span>
        <span class="mk-meta">{_esc(fmt)} &middot; {_esc(size)}</span>
      </div>
      <svg viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="mkflow" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="{VIOLET}"/>
            <stop offset="100%" stop-color="{CYAN}"/>
          </linearGradient>
        </defs>
        <g fill="url(#mkflow)">{''.join(bars)}</g>
      </svg>
    </div>
    """


def transcript_to_messages(result: TranscriptResult) -> List[Dict[str, str]]:
    """Map transcript segments to chat messages, one bubble per segment.

    Each distinct speaker is pinned to a side of the conversation (the first
    speaker on the left, the next on the right) so a two-party call reads the
    way a chat does. Speaker name and timestamp sit at the top of each bubble.
    """
    side_for_speaker: Dict[int, str] = {}
    messages: List[Dict[str, str]] = []
    for seg in result.segments:
        if seg.speaker_id not in side_for_speaker:
            side_for_speaker[seg.speaker_id] = "assistant" if len(side_for_speaker) % 2 == 0 else "user"
        header = f"**{seg.speaker_alias}**  ·  {_fmt_clock(seg.time_start)}–{_fmt_clock(seg.time_end)}"
        messages.append({"role": side_for_speaker[seg.speaker_id], "content": f"{header}\n\n{seg.text}"})
    return messages


def metrics_html(job: Job) -> str:
    result = job.result
    if not result:
        return ""
    cells = [
        ("Language", result.language or "—"),
        ("Duration", _fmt_clock(result.duration_seconds) if result.duration_seconds else "—"),
        ("Words", result.words_count if result.words_count is not None else "—"),
        ("Speakers", len({s.speaker_id for s in result.segments}) or "—"),
        ("Segments", len(result.segments)),
    ]
    inner = "".join(f"<div><small>{_esc(k)}</small><strong>{_esc(v)}</strong></div>" for k, v in cells)
    return f'<div class="mk-metrics">{inner}</div>'


# --------------------------------------------------------------------------- #
# Gradio event handlers
# --------------------------------------------------------------------------- #


def _client(token: str, api_url: str) -> KawaClient:
    return KawaClient(token=token, api_url=api_url)


def on_audio_change(file_path: Optional[str], api_url: str, language: str, metadata: str) -> Tuple[str, str]:
    """Refresh the waveform and the matching curl snippet when audio changes."""
    path = Path(file_path) if file_path else None
    return waveform_html(path), curl_create(api_url, file_path or "", language, metadata)


def on_sample_change(
    name: Optional[str], api_url: str, language: str, metadata: str
) -> Tuple[Any, str, str]:
    """Load a bundled sample into the audio component."""
    path = sample_path(name)
    file_path = str(path) if path else None
    return file_path, waveform_html(path), curl_create(api_url, file_path or "", language, metadata)


def on_curl_create(file_path: Optional[str], api_url: str, language: str, metadata: str) -> str:
    return curl_create(api_url, file_path or "", language, metadata)


def transcribe(
    file_path: Optional[str],
    token: str,
    api_url: str,
    language: str,
    metadata: str,
) -> Iterator[Tuple[str, List[Dict[str, str]], str, str, str, Any]]:
    """Upload, then poll to completion, streaming UI updates as we go.

    Yields: (status_html, chat_messages, metrics_html, raw_json, job_id, raw_open)
    The last item toggles the raw-response accordion: expanded on an error so the
    status, headers and body are in view for debugging, collapsed otherwise.
    """
    empty: List[Dict[str, str]] = []
    collapsed, expanded = gr.update(open=False), gr.update(open=True)
    if not (token or "").strip():
        yield status_pill("Add your API token under Connection to sign in.", "bad"), empty, "", "", "", collapsed
        return
    if not file_path:
        yield status_pill("Choose a sample or upload a recording first.", "bad"), empty, "", "", "", collapsed
        return

    client = _client(token, api_url)
    try:
        metadata_obj = _parse_metadata(metadata)
    except (ValueError, json.JSONDecodeError) as exc:
        yield status_pill(f"Metadata is not valid JSON: {exc}", "bad"), empty, "", "", "", collapsed
        return

    try:
        yield status_pill("Uploading recording…", "pending"), empty, "", "", "", collapsed
        job = client.create_transcription(file_path, language=language or None, metadata=metadata_obj or None)
    except (KawaError, ValueError, requests.RequestException) as exc:
        yield status_pill(f"Upload failed: {exc}", "bad"), empty, "", error_dump(exc), "", expanded
        return

    job_id = job.job_id
    queued_raw = response_dump(client.last_status, client.last_headers, job.raw)
    yield status_pill(f"Queued · {job_id}", "pending"), empty, "", queued_raw, job_id, collapsed

    try:
        for polled in client.poll(job_id):
            raw = response_dump(client.last_status, client.last_headers, polled.raw)
            if polled.status == "succeeded":
                result = polled.result
                messages = transcript_to_messages(result) if result else []
                yield (
                    status_pill("Transcript ready", "good"),
                    messages,
                    metrics_html(polled),
                    raw,
                    job_id,
                    collapsed,
                )
                return
            if polled.status == "failed":
                err = polled.error or {}
                detail = err.get("message") or err.get("code") or "The job failed."
                yield status_pill(f"Failed: {detail}", "bad"), empty, "", raw, job_id, expanded
                return
            yield status_pill(f"{polled.status.capitalize()}…", "pending"), empty, "", raw, job_id, collapsed
    except (KawaError, requests.RequestException) as exc:
        yield status_pill(f"Polling failed: {exc}", "bad"), empty, "", error_dump(exc), job_id, expanded
        return

    yield status_pill("Still processing after the polling window. Open it under Transcriptions to keep checking.", "pending"), empty, "", "", job_id, collapsed


def list_transcriptions_view(token: str, api_url: str) -> Tuple[List[List[str]], Dict[str, Any], str, str]:
    """List jobs for the Transcriptions tab.

    Returns: (table_rows, cache, list_status, list_curl)
    """
    if not (token or "").strip():
        return [], {}, status_pill("Add a token under Connection to begin.", "bad"), curl_list(api_url)
    try:
        jobs = _client(token, api_url).list_transcriptions()
    except (KawaError, requests.RequestException) as exc:
        return [], {}, status_pill(f"Could not list transcriptions: {exc}", "bad"), curl_list(api_url)

    cache: Dict[str, Any] = {}
    rows: List[List[str]] = []
    for job in jobs:
        cache[job.job_id] = job.raw
        result = job.result
        rows.append([
            job.status,
            job.raw.get("original_filename") or job.raw.get("filename") or "—",
            (result.language if result else None) or job.raw.get("language") or "—",
            job.raw.get("created_at") or job.raw.get("received_at") or job.raw.get("updated_at") or "—",
            job.job_id,
        ])
    msg = status_pill(f"{len(rows)} transcript{'s' if len(rows) != 1 else ''}", "good")
    return rows, cache, msg, curl_list(api_url)


def open_transcript(
    token: str, api_url: str, job_id: str, cache: Dict[str, Any]
) -> Tuple[List[Dict[str, str]], str, str, str, str, str, Any]:
    """Fetch one job and render it the same way as a fresh transcription.

    Returns: (chat, metrics, status, raw_json, curl_get, curl_delete, raw_open)
    The last item expands the raw-response accordion on an error, for debugging.
    """
    collapsed, expanded = gr.update(open=False), gr.update(open=True)
    job_id = (job_id or "").strip()
    curls = (curl_get(api_url, job_id), curl_delete(api_url, job_id))
    if not job_id:
        return [], "", status_pill("Select a row or paste a job id.", "bad"), "", *curls, collapsed
    if not (token or "").strip():
        return [], "", status_pill("Add a token under Connection to sign in.", "bad"), "", *curls, collapsed
    client = _client(token, api_url)
    try:
        job = client.get_transcription(job_id)
    except (KawaError, requests.RequestException) as exc:
        return [], "", status_pill(f"Could not fetch job: {exc}", "bad"), error_dump(exc), *curls, expanded

    raw = response_dump(client.last_status, client.last_headers, job.raw)
    if job.status == "succeeded" and job.result:
        return transcript_to_messages(job.result), metrics_html(job), status_pill("Transcript ready", "good"), raw, *curls, collapsed
    if job.status == "failed":
        err = job.error or {}
        detail = err.get("message") or err.get("code") or "The job failed."
        return [], "", status_pill(f"Failed: {detail}", "bad"), raw, *curls, expanded
    return [], "", status_pill(f"{job.status.capitalize()}… fetch again shortly.", "pending"), raw, *curls, collapsed


def select_row(cache: Dict[str, Any], evt: gr.SelectData) -> str:
    """Return the job id of the clicked table row (last column)."""
    try:
        rows = list(cache.keys())
        idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        return rows[int(idx)]
    except Exception:
        return ""


def delete_transcript(token: str, api_url: str, job_id: str) -> Tuple[str, str]:
    job_id = (job_id or "").strip()
    if not job_id:
        return status_pill("Paste a job id to delete.", "bad"), ""
    try:
        body = _client(token, api_url).delete_transcription(job_id)
    except (KawaError, requests.RequestException) as exc:
        return status_pill(f"Delete failed: {exc}", "bad"), ""
    return status_pill("Deleted", "good"), _pretty_json(body)


def disconnect() -> Tuple[str, str, List[List[str]], Dict[str, Any], str]:
    """Clear the token and reset the playground."""
    return (
        "",                                     # token box
        signed_in_html(""),                     # connection line
        [],                                     # jobs table
        {},                                     # cache
        status_pill("Disconnected.", ""),       # list status
    )


def add_sample_from_device(
    uploaded: Optional[str], api_url: str, language: str, metadata: str
) -> Tuple[Any, Any, str, str]:
    """Copy a device file into the sample folder so it becomes a reusable option.

    The file is saved into MAKIMOTO_SAMPLE_DIR (a unique name is chosen if one
    already exists), the dropdown is refreshed to include it and select it, and
    it is loaded as the recording to transcribe.

    Returns: (sample_dropdown_update, audio_value, waveform_html, curl_create)
    """
    if not uploaded:
        choices = list_samples()
        return gr.update(choices=choices), None, waveform_html(None), curl_create(api_url, "", language, metadata)

    src = Path(uploaded)
    ENV_SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # Use the original basename; if it clashes, append a numeric suffix.
    dest = ENV_SAMPLE_DIR / src.name
    stem, suffix, n = dest.stem, dest.suffix, 1
    while dest.exists():
        dest = ENV_SAMPLE_DIR / f"{stem}-{n}{suffix}"
        n += 1
    shutil.copyfile(src, dest)

    choices = list_samples()
    file_path = str(dest)
    return (
        gr.update(choices=choices, value=dest.name),
        file_path,
        waveform_html(dest),
        curl_create(api_url, file_path, language, metadata),
    )


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #

DEFAULT_METADATA = '{\n  "source": "playground"\n}'
JOB_TABLE_HEADERS = ["Status", "File", "Language", "Created", "Job ID"]
# Sample selected on first load; small and clean, so it works everywhere.
DEFAULT_SAMPLE = "jackhammer.wav"


def build_app() -> gr.Blocks:
    samples = list_samples()
    first_sample = DEFAULT_SAMPLE if DEFAULT_SAMPLE in samples else (samples[0] if samples else None)
    first_path = sample_path(first_sample)
    first_file = str(first_path) if first_path else None

    with gr.Blocks(title="Makimoto Kawa · Playground") as app:
        cache_state = gr.State({})

        # -- Masthead ----------------------------------------------------- #
        with gr.Row(equal_height=True):
            gr.HTML(
                f'<div class="mk-mast">{BRAND_MARK}<span class="mk-word">Makimoto</span></div>',
                padding=False,
            )
            theme_btn = gr.Button(
                "◐", variant="secondary", scale=0, min_width=46, elem_classes=["mk-iconbtn"]
            )
            disconnect_btn = gr.Button("Disconnect", variant="secondary", scale=0, min_width=120)

        gr.HTML('<div class="mk-title">Playground</div>')
        signed_in = gr.HTML(signed_in_html(ENV_TOKEN))

        # -- Connection (collapsed once a token is present) --------------- #
        with gr.Accordion("Connection", open=not bool(ENV_TOKEN)):
            with gr.Row():
                token_box = gr.Textbox(
                    label="API token",
                    value=ENV_TOKEN,
                    type="password",
                    scale=3,
                    placeholder="Bearer token from the Makimoto dashboard",
                    info="Sent as 'Authorization: Bearer …'. Kept only in this browser session.",
                )
                api_url_box = gr.Textbox(
                    label="Base URL",
                    value=ENV_API_URL,
                    scale=2,
                    info="Production: https://api.makimoto.ai",
                )
            gr.Markdown(
                "Generate a token in the [dashboard](https://makimoto.ai), or `export "
                "MAKIMOTO_API_TOKEN=…` to preload it. A `401` from the API means the token "
                "is missing, expired, or revoked.",
                elem_classes=["mk-hint"],
            )

        with gr.Tabs():
            # ============================================================= #
            # Tab 1 — Transcribe
            # ============================================================= #
            with gr.Tab("Transcribe"):
                gr.HTML(
                    '<div class="mk-lede">Turn a recording into a transcript.</div>'
                    '<div class="mk-lede-sub">Submit audio, then watch the job poll to completion. '
                    'Speaker-separated, timestamped, and rendered as the conversation it came from.</div>'
                )
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2):
                        gr.HTML(
                            '<div class="mk-endpoint"><span class="mk-method post">POST</span>'
                            '<code>/v1/transcriptions</code></div>'
                            '<div class="mk-hint">Send audio as multipart form-data. Returns a job id immediately.</div>'
                        )
                        with gr.Row(equal_height=True):
                            sample_dd = gr.Dropdown(
                                label="Bundled sample",
                                choices=samples,
                                value=first_sample,
                                scale=3,
                                info="Recordings from the sample folder.",
                            )
                            add_sample_btn = gr.UploadButton(
                                "Add from device",
                                file_types=["audio"],
                                file_count="single",
                                variant="secondary",
                                scale=1,
                                min_width=150,
                            )
                        audio_in = gr.Audio(
                            label="Recording",
                            value=first_file,
                            sources=["upload"],
                            type="filepath",
                            waveform_options=gr.WaveformOptions(waveform_color=VIOLET, waveform_progress_color=CYAN),
                        )
                        wave_html = gr.HTML(waveform_html(first_path))
                        language_box = gr.Textbox(
                            label="Language",
                            value="en",
                            placeholder="en, es, …",
                            info="Optional ISO code; auto-detected if blank.",
                        )
                        with gr.Accordion("Metadata (optional)", open=False):
                            metadata_box = gr.Code(
                                value=DEFAULT_METADATA,
                                language="json",
                                label="JSON object stored alongside the job",
                                lines=4,
                            )
                        submit_btn = gr.Button("Transcribe", variant="primary")
                        with gr.Accordion("{ } Equivalent curl", open=False):
                            create_curl = gr.Code(
                                value=curl_create(ENV_API_URL, first_file or "", "en", DEFAULT_METADATA),
                                language="shell",
                                label="Copy and run from a shell",
                            )

                    with gr.Column(scale=3):
                        transcribe_status = gr.HTML(status_pill("Ready when you are.", ""))
                        transcribe_metrics = gr.HTML("")
                        transcript_chat = gr.Chatbot(
                            label="Transcript",
                            height=460,
                            group_consecutive_messages=False,
                            placeholder="Your transcript will appear here as a conversation.",
                        )
                        job_id_out = gr.Textbox(label="Job ID", interactive=False, visible=False)
                        with gr.Accordion("{ } Raw response (status, headers, body)", open=False) as transcribe_raw_acc:
                            transcribe_raw = gr.Code(value="", language="json", label="Auto-expands on an error, for debugging")

            # ============================================================= #
            # Tab 2 — Your transcriptions
            # ============================================================= #
            with gr.Tab("Your transcriptions"):
                with gr.Row():
                    with gr.Column(scale=2):
                        with gr.Row(equal_height=True):
                            gr.HTML(
                                '<div class="mk-endpoint"><span class="mk-method get">GET</span>'
                                '<code>/v1/transcriptions</code></div>',
                                padding=False,
                            )
                            refresh_btn = gr.Button("Refresh", variant="secondary", scale=0, min_width=110)
                        list_status = gr.HTML(status_pill("Refresh to load your transcriptions.", ""))
                        jobs_table = gr.Dataframe(
                            headers=JOB_TABLE_HEADERS,
                            datatype=["str"] * len(JOB_TABLE_HEADERS),
                            interactive=False,
                            wrap=True,
                            elem_classes=["mk-table"],
                        )
                        with gr.Accordion("{ } Equivalent curl", open=False):
                            list_curl = gr.Code(value=curl_list(ENV_API_URL), language="shell", label="List jobs")
                    with gr.Column(scale=3):
                        gr.HTML(
                            '<div class="mk-endpoint"><span class="mk-method get">GET</span>'
                            '<code>/v1/transcriptions/{job_id}</code></div>'
                            '<div class="mk-hint">Click a row, or paste a job id, then open it.</div>'
                        )
                        with gr.Row():
                            detail_job_id = gr.Textbox(label="Job ID", scale=3, placeholder="00000000-0000-…")
                            open_btn = gr.Button("Open", variant="primary", scale=1, min_width=90)
                        detail_status = gr.HTML("")
                        detail_metrics = gr.HTML("")
                        detail_chat = gr.Chatbot(
                            label="Transcript",
                            height=380,
                            group_consecutive_messages=False,
                            placeholder="Select a transcript to read it here.",
                        )
                        with gr.Accordion("{ } Equivalent curl", open=False):
                            get_curl = gr.Code(value=curl_get(ENV_API_URL, ""), language="shell", label="Fetch job")
                        with gr.Accordion("{ } Raw response (status, headers, body)", open=False) as detail_raw_acc:
                            detail_raw = gr.Code(value="", language="json", label="Auto-expands on an error, for debugging")
                        with gr.Accordion("Delete this job", open=False):
                            gr.HTML(
                                '<div class="mk-endpoint"><span class="mk-method delete">DELETE</span>'
                                '<code>/v1/transcriptions/{job_id}</code></div>'
                                '<div class="mk-hint">Removes the job where the deployment supports cleanup.</div>'
                            )
                            delete_btn = gr.Button("Delete")
                            delete_status = gr.HTML("")
                            delete_curl = gr.Code(value=curl_delete(ENV_API_URL, ""), language="shell", label="Delete job")
                            delete_raw = gr.Code(value="", language="json", label="Delete response")

        # -- Wiring ------------------------------------------------------- #
        theme_btn.click(None, None, None, js=THEME_TOGGLE_JS)
        token_box.change(signed_in_html, inputs=[token_box], outputs=[signed_in])
        disconnect_btn.click(
            disconnect,
            outputs=[token_box, signed_in, jobs_table, cache_state, list_status],
        )

        # Transcribe tab
        sample_dd.change(
            on_sample_change,
            inputs=[sample_dd, api_url_box, language_box, metadata_box],
            outputs=[audio_in, wave_html, create_curl],
        )
        add_sample_btn.upload(
            add_sample_from_device,
            inputs=[add_sample_btn, api_url_box, language_box, metadata_box],
            outputs=[sample_dd, audio_in, wave_html, create_curl],
        )
        audio_in.change(
            on_audio_change,
            inputs=[audio_in, api_url_box, language_box, metadata_box],
            outputs=[wave_html, create_curl],
        )
        for comp in (language_box, metadata_box, api_url_box):
            comp.change(
                on_curl_create,
                inputs=[audio_in, api_url_box, language_box, metadata_box],
                outputs=[create_curl],
            )
        submit_btn.click(
            transcribe,
            inputs=[audio_in, token_box, api_url_box, language_box, metadata_box],
            outputs=[transcribe_status, transcript_chat, transcribe_metrics, transcribe_raw, job_id_out, transcribe_raw_acc],
        )

        refresh_btn.click(
            list_transcriptions_view,
            inputs=[token_box, api_url_box],
            outputs=[jobs_table, cache_state, list_status, list_curl],
        )

        # Transcriptions detail
        jobs_table.select(select_row, inputs=[cache_state], outputs=[detail_job_id]).then(
            open_transcript,
            inputs=[token_box, api_url_box, detail_job_id, cache_state],
            outputs=[detail_chat, detail_metrics, detail_status, detail_raw, get_curl, delete_curl, detail_raw_acc],
        )
        detail_job_id.change(
            lambda url, jid: (curl_get(url, jid), curl_delete(url, jid)),
            inputs=[api_url_box, detail_job_id],
            outputs=[get_curl, delete_curl],
        )
        open_btn.click(
            open_transcript,
            inputs=[token_box, api_url_box, detail_job_id, cache_state],
            outputs=[detail_chat, detail_metrics, detail_status, detail_raw, get_curl, delete_curl, detail_raw_acc],
        )
        delete_btn.click(
            delete_transcript,
            inputs=[token_box, api_url_box, detail_job_id],
            outputs=[delete_status, delete_raw],
        )

    return app


if __name__ == "__main__":
    host = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    # Honour GRADIO_SERVER_PORT when set; otherwise pass None so Gradio scans
    # for a free port instead of failing when 8800 is in use.
    port_env = os.getenv("GRADIO_SERVER_PORT")
    port = int(port_env) if port_env else None
    build_app().queue().launch(
        server_name=host,
        server_port=port,
        show_error=True,
        theme=make_theme(),
        css=CSS,
        head=HEAD,
        allowed_paths=[str(ROOT_DIR), "/private/tmp", "/tmp"],
    )
