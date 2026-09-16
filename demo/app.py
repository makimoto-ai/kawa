"""Makimoto Kawa - Transcription API playground.

A Gradio UI over the Makimoto transcription API: connect an API key, submit a
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
    GET    /v1/transcriptions/{job_id}   -> job status + result when succeeded
    DELETE /v1/transcriptions/{job_id}   -> remove a job (where supported)
    POST   /v1/summarize                 -> summarise a finished transcription
    POST   /v1/tag                       -> tag a finished transcription

Authenticate every request with an API key, created from the dashboard:

    Authorization: Bearer <makimoto_api_key>
"""

from __future__ import annotations

import base64
import html
import json
import os
import shutil
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import gradio as gr
import numpy as np
import requests

# The reference client lives in its own dependency-light module so it can be
# copied into a project without any of the Gradio playground below.
from kawa_client import (
    DEFAULT_API_URL,
    POSTPROCESSING_PATHS,
    Job,
    KawaClient,
    KawaError,
    SummaryResult,
    TagsResult,
    TranscriptResult,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_DIR = ROOT_DIR / "samples-audio"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}

# Environment defaults. The key is read once for convenience when developing
# locally; the UI keeps whatever you type only in the local browser session.
ENV_API_URL = os.getenv("MAKIMOTO_API_URL", DEFAULT_API_URL).rstrip("/")
ENV_API_KEY = os.getenv("MAKIMOTO_API_KEY", "")
ENV_SAMPLE_DIR = Path(os.getenv("MAKIMOTO_SAMPLE_DIR", str(DEFAULT_SAMPLE_DIR))).expanduser()

# How many jobs one page of the rail holds.
JOBS_PAGE_SIZE = 20

# What one fetch asks the API for while filling that page.
FETCH_PAGE_SIZE = 100


# --------------------------------------------------------------------------- #
# curl builders  (documentation that doubles as copy-paste shell commands)
# --------------------------------------------------------------------------- #
#
# The key is never written into these snippets; they reference the
# $MAKIMOTO_API_KEY environment variable so a copied command stays safe to
# paste into a terminal or commit to a script.


def _shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def curl_list(api_url: str, *, limit: int | None = None, cursor: str | None = None) -> str:
    """The list call, including whichever page of it the rail is showing."""
    query = "&".join(
        part
        for part in (f"limit={limit}" if limit else "", f"cursor={cursor}" if cursor else "")
        if part
    )
    url = api_url.rstrip("/") + "/v1/transcriptions" + (f"?{query}" if query else "")
    return (
        "curl -sS \\\n"
        f"  {_shell_quote(url)} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_KEY"'
    )


def curl_create(api_url: str, file_path: str, language: str, metadata: str) -> str:
    lines = [
        "curl -sS -X POST \\",
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions')} \\",
        '  -H "Authorization: Bearer $MAKIMOTO_API_KEY" \\',
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
        '  -H "Authorization: Bearer $MAKIMOTO_API_KEY"'
    )


def curl_delete(api_url: str, job_id: str) -> str:
    return (
        "curl -sS -X DELETE \\\n"
        f"  {_shell_quote(api_url.rstrip('/') + '/v1/transcriptions/' + (job_id or '<job_id>'))} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_KEY"'
    )


def curl_postprocess(api_url: str, dimension: str, source_job_id: str) -> str:
    """POST /v1/summarize or /v1/tag for one source transcription."""
    path = POSTPROCESSING_PATHS[dimension]
    body = json.dumps({"transcription_job_id": source_job_id or "<transcription_job_id>"}, separators=(",", ":"))
    return (
        "curl -sS -X POST \\\n"
        f"  {_shell_quote(api_url.rstrip('/') + path)} \\\n"
        '  -H "Authorization: Bearer $MAKIMOTO_API_KEY" \\\n'
        "  -H 'Content-Type: application/json' \\\n"
        f"  -d {_shell_quote(body)}"
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


def _parse_metadata(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return parsed


def _fmt_clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def response_dump(status: int | None, headers: dict[str, str], body: Any) -> str:
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


def list_samples(sample_dir: str | Path = ENV_SAMPLE_DIR) -> list[str]:
    directory = Path(sample_dir).expanduser()
    if not directory.exists():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def sample_path(name: str | None, sample_dir: str | Path = ENV_SAMPLE_DIR) -> Path | None:
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

# One colour per job type, for the rail badges, the legend and the detail
# heading.
TYPE_COLOURS = {"transcription": VIOLET, "summary": CYAN, "tags": "#183D82"}

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

/* Job rail ------------------------------------------------------------- */
/* A scrollable column of one button per job, newest first. Each row carries
   its type three ways: the badge drawn by the ::after rules below, the colour
   of that badge, and the colour of the left edge. The row is a plain block
   rather than a flex layout, so the badge runs on inline after the label
   instead of sitting in a column of its own, and the label wraps rather than
   truncating: a long filename or a full job id stays readable in a narrow
   rail. */
.mk-joblist {{
  max-height: 560px; overflow-y: auto; gap: 6px !important;
  border: 1px solid var(--mk-line); border-radius: 12px;
  background: var(--mk-well); padding: 8px !important; margin-bottom: 8px;
}}
.mk-joblist button.mk-jobrow {{
  display: block !important; width: 100%; text-align: left;
  white-space: normal !important; overflow-wrap: anywhere; line-height: 1.75;
  font-size: 12.5px !important; font-weight: 500;
  padding: 8px 11px !important; border-radius: 8px !important;
  background: var(--mk-panel) !important; color: var(--mk-ink) !important;
  border: 1px solid var(--mk-line) !important; border-left-width: 3px !important;
}}
/* The type badge, inline at the end of the label. A Gradio button's label is
   plain text, so the words TRANSCRIPTION / SUMMARY / TAGS come from the row's
   own class rather than being repeated into every label. */
.mk-joblist button.mk-jobrow::after {{
  display: inline-block; vertical-align: middle; white-space: nowrap;
  margin-left: 8px; position: relative; top: -1px;
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.05em;
  padding: 2px 6px; border-radius: 4px; color: #FFFFFF;
}}
.mk-joblist button.mk-jobrow:hover {{ border-color: var(--mk-violet) !important; }}
/* Scoped as tightly as the rule above, or the border shorthand there would
   win on specificity and every row would share one edge colour. */
.mk-joblist button.mk-jobrow-transcription {{ border-left-color: {TYPE_COLOURS["transcription"]} !important; }}
.mk-joblist button.mk-jobrow-transcription::after {{
  content: "TRANSCRIPTION"; background: {TYPE_COLOURS["transcription"]};
}}
.mk-joblist button.mk-jobrow-summary {{ border-left-color: {TYPE_COLOURS["summary"]} !important; }}
.mk-joblist button.mk-jobrow-summary::after {{
  content: "SUMMARY"; background: {TYPE_COLOURS["summary"]}; color: #010E39;
}}
.mk-joblist button.mk-jobrow-tags {{ border-left-color: {TYPE_COLOURS["tags"]} !important; }}
.mk-joblist button.mk-jobrow-tags::after {{ content: "TAGS"; background: {TYPE_COLOURS["tags"]}; }}
.mk-joblist button.mk-jobrow-unknown {{ border-left-color: var(--mk-muted) !important; }}
.mk-joblist button.mk-jobrow-unknown::after {{ content: "JOB"; background: var(--mk-muted); }}

/* Outcome is marked at the start of the row, so the rail can be scanned for
   trouble (or for what finished cleanly) without opening anything. ::after is
   already the type badge, which is why these lead rather than follow. The
   marker carries the outcome on its own, so the label never spells it out. */
.mk-joblist button.mk-jobrow-failed::before,
.mk-joblist button.mk-jobrow-succeeded::before {{
  display: inline-block; vertical-align: middle;
  margin-right: 7px; position: relative; top: -1px;
  width: 16px; height: 16px; border-radius: 999px;
  color: #FFFFFF;
  font-size: 11px; font-weight: 700; line-height: 16px; text-align: center;
}}
.mk-joblist button.mk-jobrow-failed::before {{ content: "!"; background: var(--mk-bad); }}
.mk-joblist button.mk-jobrow-succeeded::before {{ content: "\\2713"; background: var(--mk-good); }}

/* Legend: the same three badges, so the rail needs no explaining. */
.mk-legend {{ display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 2px 0 8px; }}
.mk-legend small {{
  color: var(--mk-muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.06em; margin-right: 2px;
}}

/* Type tag + detail heading -------------------------------------------- */
.mk-jobhead {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 2px 0 8px; }}
.mk-jobhead code {{ font-size: 12.5px; color: var(--mk-muted); background: transparent; }}
.mk-tag {{
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 3px 9px; border-radius: 5px; color: #FFFFFF;
}}
.mk-tag-transcription {{ background: {TYPE_COLOURS["transcription"]}; }}
.mk-tag-summary {{ background: {TYPE_COLOURS["summary"]}; color: #010E39; }}
.mk-tag-tags {{ background: {TYPE_COLOURS["tags"]}; }}
.mk-tag-unknown {{ background: var(--mk-muted); }}

/* Derived result blocks ------------------------------------------------- */
.mk-derived {{ margin-top: 10px; }}
.mk-derived > small {{
  display: block; color: var(--mk-muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 5px;
}}

/* Summary + tags ------------------------------------------------------- */
.mk-card {{
  border: 1px solid var(--mk-line); border-radius: 12px; background: var(--mk-well);
  padding: 14px 16px; margin: 4px 0 2px;
}}
.mk-card .mk-topic {{
  display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--mk-code-ink);
  border: 1px solid var(--mk-line); border-radius: 999px; padding: 3px 10px; margin-bottom: 10px;
}}
.mk-card p {{ margin: 0; font-size: 14.5px; line-height: 1.6; color: var(--mk-ink); }}

.mk-cat {{ margin-top: 12px; }}
.mk-cat:first-child {{ margin-top: 0; }}
.mk-cat small {{
  display: block; color: var(--mk-muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;
}}
.mk-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.mk-chip {{
  font-size: 12.5px; font-weight: 500; color: var(--mk-ink);
  background: var(--mk-panel); border: 1px solid var(--mk-line);
  border-radius: 999px; padding: 3px 11px;
}}

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
    var pref = 'dark';
    try { pref = localStorage.getItem('mk-theme') || 'dark'; } catch (e) {}
    var isDark = pref !== 'light';

    document.documentElement.classList.toggle('dark', isDark);
    if (document.body) {
        document.body.classList.toggle('dark', isDark);
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            if (document.body) document.body.classList.toggle('dark', isDark);
        }, { once: true });
    }
})();
</script>
"""

# Masthead toggle: flip the .dark class on <html>, persist the choice, no reload.
THEME_TOGGLE_JS = """
() => {
    var isDark = !document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', isDark);
    if (document.body) document.body.classList.toggle('dark', isDark);
    try { localStorage.setItem('mk-theme', isDark ? 'dark' : 'light'); } catch (e) {}
}
"""


# --------------------------------------------------------------------------- #
# View helpers  (turn API data into the UI)
# --------------------------------------------------------------------------- #


def status_pill(text: str, kind: str = "") -> str:
    return f'<div class="mk-status {kind}"><span class="mk-dot"></span><span>{_esc(text)}</span></div>'


def _decode_jwt(token: str) -> dict[str, Any] | None:
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
        return '<div class="mk-subtle">Not connected. Add an API key under Connection to begin.</div>'
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


def waveform_html(path: Path | None) -> str:
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


def transcript_to_messages(result: TranscriptResult) -> list[dict[str, str]]:
    """Map transcript segments to chat messages, one bubble per segment.

    Each distinct speaker is pinned to a side of the conversation (the first
    speaker on the left, the next on the right) so a two-party call reads the
    way a chat does. Speaker name and timestamp sit at the top of each bubble.
    """
    side_for_speaker: dict[int, str] = {}
    messages: list[dict[str, str]] = []
    for seg in result.segments:
        if seg.speaker_id not in side_for_speaker:
            side_for_speaker[seg.speaker_id] = "assistant" if len(side_for_speaker) % 2 == 0 else "user"
        header = f"**{seg.speaker_alias}**  ·  {_fmt_clock(seg.time_start)}–{_fmt_clock(seg.time_end)}"
        messages.append({"role": side_for_speaker[seg.speaker_id], "content": f"{header}\n\n{seg.text}"})
    return messages


def summary_html(result: SummaryResult) -> str:
    """A summary as a topic pill above the prose."""
    topic = f'<span class="mk-topic">{_esc(result.topic)}</span>' if result.topic else ""
    body = _esc(result.summary) or "The model returned an empty summary."
    return f'<div class="mk-card">{topic}<p>{body}</p></div>'


def tags_html(result: TagsResult) -> str:
    """A tag set as one chip row per category.

    Category keys arrive lower_snake_case (``call_reason``,
    ``customer_sentiment``), as do the values; both are humanised for display
    while the raw form stays visible in the response panel.
    """
    if not result.tags:
        return '<div class="mk-card"><p>The model selected no tags.</p></div>'
    blocks = []
    for category, values in result.tags.items():
        chips = "".join(f'<span class="mk-chip">{_esc(v.replace("_", " "))}</span>' for v in values)
        blocks.append(
            f'<div class="mk-cat"><small>{_esc(category.replace("_", " "))}</small>'
            f'<div class="mk-chips">{chips}</div></div>'
        )
    return f'<div class="mk-card">{"".join(blocks)}</div>'


# The three job types, as the API names them in a job's ``type`` field.
# "unknown" is the playground's own fourth case: a listed job whose type could
# not be resolved, which opening it will settle.
JOB_TYPE_LABELS = {"transcription": "Transcription", "summary": "Summary", "tags": "Tags", "unknown": "Job"}


def postprocessing_html(job: Job) -> str:
    """Render whichever of the two result shapes the job carries."""
    if job.type == "summary" and job.summary:
        return summary_html(job.summary)
    if job.type == "tags" and job.tags:
        return tags_html(job.tags)
    return ""


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
    return KawaClient(key=token, api_url=api_url)


def on_audio_change(file_path: str | None, api_url: str, language: str, metadata: str) -> tuple[str, str]:
    """Refresh the waveform and the matching curl snippet when audio changes."""
    path = Path(file_path) if file_path else None
    return waveform_html(path), curl_create(api_url, file_path or "", language, metadata)


def on_sample_change(
    name: str | None, api_url: str, language: str, metadata: str
) -> tuple[Any, str, str]:
    """Load a bundled sample into the audio component."""
    path = sample_path(name)
    file_path = str(path) if path else None
    return file_path, waveform_html(path), curl_create(api_url, file_path or "", language, metadata)


def on_curl_create(file_path: str | None, api_url: str, language: str, metadata: str) -> str:
    return curl_create(api_url, file_path or "", language, metadata)


def transcribe(
    file_path: str | None,
    token: str,
    api_url: str,
    language: str,
    metadata: str,
) -> Iterator[tuple[str, list[dict[str, str]], str, str, str, Any]]:
    """Upload, then poll to completion, streaming UI updates as we go.

    Yields: (status_html, chat_messages, metrics_html, raw_json, job_id, raw_open)
    The last item toggles the raw-response accordion: expanded on an error so the
    status, headers and body are in view for debugging, collapsed otherwise.
    """
    empty: list[dict[str, str]] = []
    collapsed, expanded = gr.update(open=False), gr.update(open=True)
    if not (token or "").strip():
        yield status_pill("Add your API key under Connection to sign in.", "bad"), empty, "", "", "", collapsed
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


def _job_filename(job: Job) -> str | None:
    name = job.raw.get("original_filename") or job.raw.get("filename")
    return str(name) if name else None


def _resolve_type(token: str, api_url: str, job_id: str) -> tuple[str, str]:
    """Fetch one job purely to learn its ``type``.

    Given its own client, and therefore its own ``requests.Session``, because
    these run on a thread pool and a Session is not safe to share. A failure
    reports ``unknown`` rather than guessing: the row still lists, and opening
    it resolves the type properly.
    """
    try:
        return job_id, KawaClient(key=token, api_url=api_url).get_transcription(job_id).type
    except (KawaError, requests.RequestException, ValueError):
        return job_id, "unknown"


def _rows_for(
    jobs: list[Job], token: str, api_url: str, types: dict[str, str]
) -> list[dict[str, str]]:
    """Turn one page of jobs into rail rows, labelled by job type.

    Job types are cached for the session (``types`` is updated in place) and a later
    page or refresh only resolves rows it has not seen before.
    """
    unresolved = [j.job_id for j in jobs if not _job_filename(j) and j.job_id not in types]
    if unresolved:
        with ThreadPoolExecutor(max_workers=min(8, len(unresolved))) as pool:
            for job_id, kind in pool.map(lambda jid: _resolve_type(token, api_url, jid), unresolved):
                types[job_id] = kind

    return [
        {
            "job_id": job.job_id,
            "type": "transcription" if _job_filename(job) else types.get(job.job_id, "unknown"),
            "status": job.status,
            "name": _job_filename(job) or "",
            "created": str(job.raw.get("created_at") or job.raw.get("received_at") or ""),
        }
        for job in jobs
    ]


def _is_filtered(filters: tuple[str, str, str]) -> bool:
    """Whether any of the (type, status, since) filters narrows."""
    type_filter, status_filter, since_filter = filters
    if any(f not in ("", "all") for f in (type_filter, status_filter)):
        return True
    return bool((since_filter or "").strip())


def _jobs_loaded_pill(total: int, loaded: int, filtered: bool) -> str:
    """The rail's status line: the account's total, then how much is on screen."""
    jobs = f"{total} job{'s' if total != 1 else ''}"
    return status_pill(f"{jobs} · {loaded} {'matching ' if filtered else ''}loaded", "good")


def _fill_page(
    client: KawaClient,
    token: str,
    api_url: str,
    types: dict[str, str],
    cursor: str | None,
    filters: tuple[str, str, str],
    want: int = JOBS_PAGE_SIZE,
) -> tuple[list[dict[str, str]], str | None]:
    """Walk pages from ``cursor`` until ``want`` rows match, or they run out.

    Returns the matching rows and the cursor to resume from, which is ``None` `once the account's list is exhausted.
    """
    filtering = _is_filtered(filters)
    limit = FETCH_PAGE_SIZE if filtering else want
    matched: list[dict[str, str]] = []
    while len(matched) < want:
        page = client.list_transcriptions(limit=limit, cursor=cursor)
        matched.extend(_rows_matching(_rows_for(page.jobs, token, api_url, types), *filters))
        cursor = page.next_cursor
        if not cursor:
            return matched, None
    return matched, cursor


def list_jobs_view(
    token: str,
    api_url: str,
    known_types: dict[str, str],
    type_filter: str = "all",
    status_filter: str = "all",
    since_filter: str = "",
) -> tuple[list[dict[str, str]], dict[str, str], str, str, str | None, Any, int]:
    """GET /v1/transcriptions - the newest jobs matching the filters.

    Returns: (rows, type_cache, list_status, list_curl, next_cursor, more_btn, total)
    """
    types = dict(known_types or {})
    filters = (type_filter, status_filter, since_filter)
    filtered = _is_filtered(filters)
    if not (token or "").strip():
        return (
            [], types,
            status_pill("Add an API key under Connection to begin.", "bad"),
            curl_list(api_url), None, gr.update(visible=False), 0,
        )
    try:
        client = _client(token, api_url)
        rows, cursor = _fill_page(client, token, api_url, types, None, filters)
        total = client.count_transcriptions()
    except (KawaError, requests.RequestException) as exc:
        return (
            [], types,
            status_pill(f"Could not list your jobs: {exc}", "bad"),
            curl_list(api_url), None, gr.update(visible=False), 0,
        )

    # The API already orders by created_at descending; sorting again makes
    # "latest run first" a property of the list rather than of the endpoint.
    rows.sort(key=lambda row: row["created"], reverse=True)
    return (
        rows, types,
        _jobs_loaded_pill(total, len(rows), filtered),
        curl_list(api_url, limit=FETCH_PAGE_SIZE),
        cursor,
        gr.update(visible=bool(cursor)),
        total,
    )


def load_more_jobs_view(
    token: str,
    api_url: str,
    known_types: dict[str, str],
    rows: list[dict[str, str]],
    cursor: str | None,
    total: int,
    type_filter: str,
    status_filter: str,
    since_filter: str,
) -> tuple[list[dict[str, str]], dict[str, str], str, str, str | None, Any, int]:
    """Another page of matches, appended to what the rail already shows.

    Returns: (rows, type_cache, list_status, list_curl, next_cursor, more_btn, total)
    """
    types = dict(known_types or {})
    loaded = list(rows or [])
    filters = (type_filter, status_filter, since_filter)
    filtered = _is_filtered(filters)
    if not cursor:
        return (
            loaded, types,
            _jobs_loaded_pill(total, len(loaded), filtered),
            curl_list(api_url, limit=FETCH_PAGE_SIZE), None, gr.update(visible=False), total,
        )
    try:
        client = _client(token, api_url)
        fresh, next_cursor = _fill_page(client, token, api_url, types, cursor, filters)
    except (KawaError, requests.RequestException) as exc:
        return (
            loaded, types,
            status_pill(f"Could not load more jobs: {exc}", "bad"),
            curl_list(api_url, limit=FETCH_PAGE_SIZE, cursor=cursor), cursor, gr.update(visible=True), total,
        )

    # A job already on the rail is not added twice: a job created between two
    # page fetches shifts the window, and can otherwise arrive on both sides.
    seen = {row["job_id"] for row in loaded}
    combined = loaded + [row for row in fresh if row["job_id"] not in seen]
    combined.sort(key=lambda row: row["created"], reverse=True)
    return (
        combined, types,
        _jobs_loaded_pill(total, len(combined), filtered),
        curl_list(api_url, limit=FETCH_PAGE_SIZE, cursor=next_cursor),
        next_cursor,
        gr.update(visible=bool(next_cursor)),
        total,
    )


def row_label(row: dict[str, str]) -> str:
    """What a rail row says, after its type badge."""
    when = (row["created"][:16] or "").replace("T", " ") or "no date"
    what = row["name"] or row["job_id"]
    suffix = "" if row["status"] in ("succeeded", "failed") else f"  ·  {row['status']}"
    return f"{what}  ·  {when}{suffix}"


def row_classes(row: dict[str, str]) -> list[str]:
    """Classes for one rail row: its type badge, and its outcome marker.

    Both are drawn in CSS rather than written into the button's label, which
    can only hold plain text. Only the two terminal outcomes get a marker; a
    job still queued or processing has none, and says so in its label instead.
    """
    classes = ["mk-jobrow", f"mk-jobrow-{row['type']}"]
    if row["status"] in ("succeeded", "failed"):
        classes.append(f"mk-jobrow-{row['status']}")
    return classes


def rail_legend_html() -> str:
    """The badge for each job type, keyed to the colours used in the rail."""
    chips = "".join(
        f'<span class="mk-tag mk-tag-{kind}">{_esc(JOB_TYPE_LABELS[kind])}</span>'
        for kind in ("transcription", "summary", "tags")
    )
    return f'<div class="mk-legend"><small>Job types</small>{chips}</div>'


def _rows_matching(
    rows: list[dict[str, str]], type_filter: str, status_filter: str, since_filter: str
) -> list[dict[str, str]]:
    """Which rail rows survive the type/status/since filters, in one pass."""
    since = (since_filter or "").strip()
    return [
        row
        for row in rows
        if type_filter in ("", "all") or row["type"] == type_filter
        if status_filter in ("", "all") or row["status"] == status_filter
        if not since or row["created"][:10] >= since
    ]


def _upsert_row(rows: list[dict[str, str]], row: dict[str, str]) -> list[dict[str, str]]:
    """Put a just-created or just-finished job at the top of the rail."""
    return [row, *[r for r in (rows or []) if r["job_id"] != row["job_id"]]]


# --------------------------------------------------------------------------- #
# The detail panel
# --------------------------------------------------------------------------- #
#
# One job's worth of UI, whichever of the three types it turns out to be, so
# every path through open_job returns the same shape. _detail() fills in the
# defaults (everything empty, every conditional section hidden) and each caller
# overrides only the fields it has something to say about.

DETAIL_FIELDS = (
    "head", "job_id", "source", "source_note", "status",
    "metrics", "chat", "transcript_visible",
    "result", "result_visible",
    "actions_visible", "pp_status", "summary", "tags",
    "raw", "raw_open",
    "get_curl", "delete_curl", "summarize_curl", "tag_curl",
)


def _detail(**overrides: Any) -> tuple[Any, ...]:
    fields: dict[str, Any] = {
        "head": "",
        "job_id": "",
        "source": gr.update(value="", visible=False),
        "source_note": gr.update(visible=False),
        "status": "",
        "metrics": "",
        "chat": [],
        "transcript_visible": gr.update(visible=False),
        "result": "",
        "result_visible": gr.update(visible=False),
        "actions_visible": gr.update(visible=False),
        "pp_status": "",
        "summary": "",
        "tags": "",
        "raw": "",
        "raw_open": gr.update(open=False),
        "get_curl": "",
        "delete_curl": "",
        "summarize_curl": "",
        "tag_curl": "",
    }
    fields.update(overrides)
    return tuple(fields[name] for name in DETAIL_FIELDS)


def job_head_html(kind: str, job_id: str) -> str:
    label = JOB_TYPE_LABELS.get(kind, "Job")
    return (
        f'<div class="mk-jobhead"><span class="mk-tag mk-tag-{_esc(kind)}">{_esc(label)}</span>'
        f"<code>{_esc(job_id)}</code></div>"
    )


def job_status_pill(job: Job) -> str:
    ready = {"transcription": "Transcript ready", "summary": "Summary ready", "tags": "Tags ready"}
    if job.status == "succeeded":
        return status_pill(ready.get(job.type, "Ready"), "good")
    if job.status == "failed":
        err = job.error or {}
        return status_pill(f"Failed: {err.get('message') or err.get('code') or 'The job failed.'}", "bad")
    return status_pill(f"{job.status.capitalize()}… open it again shortly.", "pending")


def derived_block(title: str, job_id: str, inner: str) -> str:
    """Wrap a summary or tag set with the id of the job that produced it."""
    return f'<div class="mk-derived"><small>{_esc(title)} · {_esc(job_id)}</small>{inner}</div>'


def fetch_derived(client: KawaClient, dimension: str, job_id: str | None) -> str:
    """Render a postprocessing job that was derived from the open transcript."""
    if not job_id:
        return ""
    title = JOB_TYPE_LABELS[dimension]
    try:
        job = client.get_transcription(job_id)
    except (KawaError, requests.RequestException) as exc:
        return derived_block(title, job_id, f'<div class="mk-empty">Could not fetch it: {_esc(exc)}</div>')
    if job.status == "succeeded":
        return derived_block(title, job_id, postprocessing_html(job))
    if job.status == "failed":
        err = job.error or {}
        detail = err.get("message") or err.get("code") or "the job failed"
        return derived_block(title, job_id, f'<div class="mk-empty">Failed: {_esc(detail)}.</div>')
    return derived_block(title, job_id, status_pill(f"{job.status.capitalize()}… reopen this job to check.", "pending"))


def open_job(job_id: str, token: str, api_url: str, pairs: dict[str, Any]) -> tuple[Any, ...]:
    """Fetch one job and lay it out according to its type.

    A transcription gets its transcript, the two postprocessing buttons, and
    whatever has already been derived from it. A summary or tags job gets its
    result and the transcription it came from, which is known only because
    this playground recorded the pairing: see ``record_pair``.
    """
    collapsed, expanded = gr.update(open=False), gr.update(open=True)
    job_id = (job_id or "").strip()
    curls = {
        "get_curl": curl_get(api_url, job_id),
        "delete_curl": curl_delete(api_url, job_id),
        "summarize_curl": curl_postprocess(api_url, "summary", job_id),
        "tag_curl": curl_postprocess(api_url, "tags", job_id),
    }
    if not job_id:
        return _detail(status=status_pill("Pick a job from the list.", ""), **curls)
    if not (token or "").strip():
        return _detail(status=status_pill("Add an API key under Connection to sign in.", "bad"), **curls)

    client = _client(token, api_url)
    try:
        job = client.get_transcription(job_id)
    except (KawaError, requests.RequestException) as exc:
        return _detail(
            job_id=job_id,
            status=status_pill(f"Could not fetch job: {exc}", "bad"),
            raw=error_dump(exc),
            raw_open=expanded,
            **curls,
        )

    raw = response_dump(client.last_status, client.last_headers, job.raw)
    common = {
        "head": job_head_html(job.type, job_id),
        "job_id": job_id,
        "status": job_status_pill(job),
        "raw": raw,
        "raw_open": expanded if job.status == "failed" else collapsed,
        **curls,
    }

    if job.type == "transcription":
        derived = (pairs or {}).get("by_source", {}).get(job_id, {})
        return _detail(
            metrics=metrics_html(job),
            chat=transcript_to_messages(job.result) if job.result else [],
            transcript_visible=gr.update(visible=True),
            # Nothing can be derived from a job that has not succeeded, so the
            # buttons stay hidden rather than offering a guaranteed 409.
            actions_visible=gr.update(visible=job.status == "succeeded"),
            summary=fetch_derived(client, "summary", derived.get("summary")),
            tags=fetch_derived(client, "tags", derived.get("tags")),
            **common,
        )

    # The API reports the source itself now. The browser's own record is the
    # fallback, for a job created before that landed, or against a deployment
    # that predates the field.
    source_id = job.source_job_id or (pairs or {}).get("by_result", {}).get(job_id)
    return _detail(
        source=gr.update(value=source_id or "", visible=bool(source_id)),
        source_note=gr.update(visible=not source_id),
        result=postprocessing_html(job),
        result_visible=gr.update(visible=True),
        **common,
    )


# --------------------------------------------------------------------------- #
# Postprocessing  (summarise / tag the open transcription)
# --------------------------------------------------------------------------- #


def record_pair(pairs: dict[str, Any], source_id: str, dimension: str, result_id: str) -> dict[str, Any]:
    """Remember which transcription a summary or tags job came from.

    The API does not: a postprocessing job row carries no reference to its
    source, and neither does the 202 that creates it. Without this the lineage
    is simply lost, so the playground keeps its own record in browser storage,
    which is why it survives a reload but not a different browser, and knows
    nothing about jobs created elsewhere.
    """
    pairs = dict(pairs or {})
    by_source = {k: dict(v) for k, v in (pairs.get("by_source") or {}).items()}
    by_result = dict(pairs.get("by_result") or {})
    by_source.setdefault(source_id, {})[dimension] = result_id
    by_result[result_id] = source_id
    return {"by_source": by_source, "by_result": by_result}


def run_postprocess(
    dimension: str,
    source_job_id: str,
    token: str,
    api_url: str,
    pairs: dict[str, Any],
    rows: list[dict[str, str]],
) -> Iterator[tuple[Any, ...]]:
    """POST /v1/summarize or /v1/tag for the open transcription, then poll.

    The POST answers 202 with a *new* job id, and that is what gets polled. The
    new job is written into the rail straight away so it is visible as it runs,
    and the pairing is recorded at creation rather than on success, so lineage
    survives a job that fails or outlives the polling window.

    Yields: (pp_status, summary, tags, raw, raw_open, pairs, rows)
    ``summary`` and ``tags`` share one handler; the dimension not being run is
    left untouched with gr.skip().
    """
    noun = JOB_TYPE_LABELS[dimension]
    skip = gr.skip()
    collapsed, expanded = gr.update(open=False), gr.update(open=True)

    def emit(
        pp_status: str,
        block: Any = skip,
        raw: Any = skip,
        raw_open: Any = skip,
        pairs_out: Any = skip,
        rows_out: Any = skip,
    ) -> tuple[Any, ...]:
        return (
            pp_status,
            block if dimension == "summary" else skip,
            block if dimension == "tags" else skip,
            raw,
            raw_open,
            pairs_out,
            rows_out,
        )

    source_job_id = (source_job_id or "").strip()
    if not (token or "").strip():
        yield emit(status_pill("Add your API key under Connection to sign in.", "bad"))
        return
    if not source_job_id:
        yield emit(status_pill("Open a transcription first.", "bad"))
        return

    client = _client(token, api_url)
    yield emit(status_pill(f"Submitting for {noun.lower()}…", "pending"))
    try:
        job = client.create_postprocessing(dimension, source_job_id)
    except (KawaError, ValueError, requests.RequestException) as exc:
        # The codes are distinct on purpose: 409 means "still running, retry
        # later", 400 NOT_A_TRANSCRIPTION means the wrong kind of job.
        yield emit(status_pill(f"{noun} request refused: {exc}", "bad"), "", error_dump(exc), expanded)
        return

    job_id = job.job_id
    pairs = record_pair(pairs, source_job_id, dimension, job_id)
    row = {
        "job_id": job_id,
        "type": dimension,
        "status": job.status or "processing",
        "name": "",
        "created": str(job.raw.get("received_at") or job.raw.get("created_at") or ""),
    }
    yield emit(
        status_pill(f"Accepted · {job_id}", "pending"),
        derived_block(noun, job_id, status_pill("Queued with the provider…", "pending")),
        response_dump(client.last_status, client.last_headers, job.raw),
        collapsed,
        pairs,
        _upsert_row(rows, row),
    )

    try:
        for polled in client.poll(job_id):
            raw = response_dump(client.last_status, client.last_headers, polled.raw)
            if polled.is_terminal:
                finished = {**row, "status": polled.status}
                if polled.status == "succeeded":
                    yield emit(
                        status_pill(f"{noun} ready", "good"),
                        derived_block(noun, job_id, postprocessing_html(polled)),
                        raw, collapsed, skip, _upsert_row(rows, finished),
                    )
                    return
                err = polled.error or {}
                detail = err.get("message") or err.get("code") or "The job failed."
                yield emit(
                    status_pill(f"Failed: {detail}", "bad"),
                    derived_block(noun, job_id, f'<div class="mk-empty">Failed: {_esc(detail)}</div>'),
                    raw, expanded, skip, _upsert_row(rows, finished),
                )
                return
            yield emit(
                status_pill(f"{polled.status.capitalize()}…", "pending"),
                derived_block(noun, job_id, status_pill(f"{polled.status.capitalize()}…", "pending")),
                raw, collapsed,
            )
    except (KawaError, requests.RequestException) as exc:
        yield emit(status_pill(f"Polling failed: {exc}", "bad"), skip, error_dump(exc), expanded)
        return

    yield emit(
        status_pill(f"Still processing after the polling window. Open {job_id} from the list later.", "pending"),
        derived_block(noun, job_id, status_pill("Still processing.", "pending")),
    )


def summarize(
    source_job_id: str, token: str, api_url: str, pairs: dict[str, Any], rows: list[dict[str, str]]
) -> Iterator[tuple[Any, ...]]:
    yield from run_postprocess("summary", source_job_id, token, api_url, pairs, rows)


def tag(
    source_job_id: str, token: str, api_url: str, pairs: dict[str, Any], rows: list[dict[str, str]]
) -> Iterator[tuple[Any, ...]]:
    yield from run_postprocess("tags", source_job_id, token, api_url, pairs, rows)


def delete_transcript(token: str, api_url: str, job_id: str) -> tuple[str, str]:
    job_id = (job_id or "").strip()
    if not job_id:
        return status_pill("Open a job to delete it.", "bad"), ""
    try:
        body = _client(token, api_url).delete_transcription(job_id)
    except (KawaError, requests.RequestException) as exc:
        return status_pill(f"Delete failed: {exc}", "bad"), ""
    return status_pill("Deleted", "good"), _pretty_json(body)


def disconnect() -> tuple[str, str, list[dict[str, str]], dict[str, str], str, None, Any, int]:
    """Clear the API key and reset the playground.

    The recorded pairings are left alone: they are job ids this browser
    produced, not credentials, and they are what makes a summary's source
    traceable after signing back in.
    """
    return (
        "",                                     # token box (holds the API key)
        signed_in_html(""),                     # connection line
        [],                                     # job rail
        {},                                     # resolved-type cache
        status_pill("Disconnected.", ""),       # list status
        None,                                   # pagination cursor
        gr.update(visible=False),               # load-more button
        0,                                      # job total
    )


def add_sample_from_device(
    uploaded: str | None, api_url: str, language: str, metadata: str
) -> tuple[Any, Any, str, str]:
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
# Sample selected on first load; small and clean, so it works everywhere.
DEFAULT_SAMPLE = "jackhammer.wav"


def build_app() -> gr.Blocks:
    samples = list_samples()
    first_sample = DEFAULT_SAMPLE if DEFAULT_SAMPLE in samples else (samples[0] if samples else None)
    first_path = sample_path(first_sample)
    first_file = str(first_path) if first_path else None

    with gr.Blocks(title="Makimoto Kawa · Playground") as app:
        # The job rail's rows, newest first, and the resolved type of each job
        # id seen so far (a type never changes, so it is only looked up once).
        jobs_state = gr.State([])
        types_state = gr.State({})
        # The cursor for the page after the one the rail is showing, or None
        # once the walk has reached the end, and the account's job total that
        # the same refresh counted. Both reset by every refresh.
        cursor_state = gr.State(None)
        total_state = gr.State(0)
        # Which transcription each summary or tags job came from. The API keeps
        # no such link, so this is the only record of it; browser storage means
        # it survives a reload without ever reaching the server.
        pairs_state = gr.BrowserState(
            {"by_source": {}, "by_result": {}}, storage_key="mk-postprocessing-pairs"
        )

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
        signed_in = gr.HTML(signed_in_html(ENV_API_KEY))

        # -- Connection (collapsed once an API key is present) ------------ #
        with gr.Accordion("Connection", open=not bool(ENV_API_KEY)):
            with gr.Row():
                token_box = gr.Textbox(
                    label="API key",
                    value=ENV_API_KEY,
                    type="password",
                    scale=3,
                    placeholder="API key from the Makimoto dashboard",
                    info="Sent as 'Authorization: Bearer …'. Kept only in this browser session.",
                )
                api_url_box = gr.Textbox(
                    label="Base URL",
                    value=ENV_API_URL,
                    scale=2,
                )
            gr.Markdown(
                "Generate an API key in the [dashboard](https://makimoto.ai), or `export "
                "MAKIMOTO_API_KEY=…` to preload it. A `401` from the API means the key "
                "is missing, expired, or revoked.",
                elem_classes=["mk-hint"],
            )

        with gr.Tabs() as tabs:
            # ============================================================= #
            # Tab 1 — Transcribe
            # ============================================================= #
            with gr.Tab("Transcribe", id="transcribe"):
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
                        with gr.Row(equal_height=True):
                            job_id_out = gr.Textbox(
                                label="Job ID",
                                interactive=False,
                                buttons=["copy"],
                                scale=3,
                                info="Copy it, or carry it straight over to summarise or tag this call.",
                            )
                            transcribe_pp_btn = gr.Button(
                                "Summarise or tag", variant="secondary", scale=1, min_width=150
                            )
                        with gr.Accordion("{ } Raw response (status, headers, body)", open=False) as transcribe_raw_acc:
                            transcribe_raw = gr.Code(value="", language="json", label="Auto-expands on an error, for debugging")

            # ============================================================= #
            # Tab 2 — Your jobs  (rail on the left, one job's detail on the right)
            # ============================================================= #
            with gr.Tab("Your jobs", id="jobs"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2):
                        with gr.Row(equal_height=True):
                            gr.HTML(
                                '<div class="mk-endpoint"><span class="mk-method get">GET</span>'
                                '<code>/v1/transcriptions</code></div>',
                                padding=False,
                            )
                            refresh_btn = gr.Button("Refresh", variant="secondary", scale=0, min_width=110)
                        list_status = gr.HTML(status_pill("Refresh to load your jobs.", ""))
                        gr.HTML(rail_legend_html(), padding=False)

                        with gr.Row(equal_height=True):
                            type_filter_dd = gr.Dropdown(
                                label="Type",
                                choices=[
                                    ("All types", "all"),
                                    ("Transcription", "transcription"),
                                    ("Summary", "summary"),
                                    ("Tags", "tags"),
                                ],
                                value="all",
                                scale=1,
                            )
                            status_filter_dd = gr.Dropdown(
                                label="Outcome",
                                choices=[("All", "all"), ("Succeeded", "succeeded"), ("Failed", "failed")],
                                value="all",
                                scale=1,
                            )
                            since_filter_box = gr.Textbox(
                                label="Since",
                                placeholder="YYYY-MM-DD",
                                scale=1,
                            )

                        with gr.Column(elem_classes=["mk-joblist"]):
                            @gr.render(inputs=[jobs_state])
                            def render_job_rail(rows: list[dict[str, str]]):
                                if not rows:
                                    gr.HTML(
                                        '<div class="mk-empty">Nothing to show. Refresh to list your '
                                        "transcriptions, summaries and tag sets, or widen the filters."
                                        "</div>"
                                    )
                                    return
                                for row in rows:
                                    gr.Button(
                                        row_label(row),
                                        variant="secondary",
                                        elem_classes=row_classes(row),
                                    ).click(
                                        # Default argument, not a closure over
                                        # the loop variable, so every row keeps
                                        # the id it was rendered with.
                                        lambda token, api_url, pairs, jid=row["job_id"]: open_job(
                                            jid, token, api_url, pairs
                                        ),
                                        inputs=[token_box, api_url_box, pairs_state],
                                        outputs=detail_outputs,
                                    )

                        # Hidden until a fetch reports a next_cursor, and hidden
                        # again on the page that reports none.
                        more_btn = gr.Button("Load more", variant="secondary", visible=False)

                        with gr.Accordion("{ } Equivalent curl", open=False):
                            list_curl = gr.Code(value=curl_list(ENV_API_URL), language="shell", label="List jobs")

                    with gr.Column(scale=3):
                        gr.HTML(
                            '<div class="mk-endpoint"><span class="mk-method get">GET</span>'
                            '<code>/v1/transcriptions/{job_id}</code></div>'
                            '<div class="mk-hint">Click a job on the left to open it here.</div>'
                        )
                        detail_head = gr.HTML("")
                        detail_job_id = gr.Textbox(
                            label="Job ID", interactive=False, buttons=["copy"], placeholder="00000000-0000-…"
                        )
                        source_box = gr.Textbox(
                            label="Source transcription job ID",
                            interactive=False,
                            visible=False,
                            buttons=["copy"],
                            info=(
                                "Reported by the API as 'source_job_id', falling back to this "
                                "browser's own record of what it created."
                            ),
                        )
                        source_note = gr.HTML(
                            '<div class="mk-empty">Source transcription unknown. The job was created '
                            "before the API began recording where a summary or tags job came from, or "
                            "by another client, and this browser has no record of it either.</div>",
                            visible=False,
                        )
                        detail_status = gr.HTML("")

                        with gr.Column(visible=False) as transcript_group:
                            detail_metrics = gr.HTML("")
                            detail_chat = gr.Chatbot(
                                label="Transcript",
                                height=380,
                                group_consecutive_messages=False,
                                placeholder="Select a transcript to read it here.",
                            )

                        with gr.Column(visible=False) as result_group:
                            detail_result = gr.HTML("")

                        with gr.Column(visible=False) as actions_group:
                            gr.HTML(
                                '<div class="mk-endpoint"><span class="mk-method post">POST</span>'
                                '<code>/v1/summarize</code>'
                                '<span class="mk-method post">POST</span><code>/v1/tag</code></div>'
                                '<div class="mk-hint">Each derives a new job from this transcript and '
                                'appears in the rail on the left.</div>'
                            )
                            with gr.Row(equal_height=True):
                                summarize_btn = gr.Button("Summarise", variant="primary")
                                tag_btn = gr.Button("Tag", variant="primary")
                            pp_status = gr.HTML("")
                            derived_summary = gr.HTML("")
                            derived_tags = gr.HTML("")

                        with gr.Accordion("{ } Equivalent curl", open=False):
                            get_curl = gr.Code(value=curl_get(ENV_API_URL, ""), language="shell", label="Fetch job")
                            summarize_curl = gr.Code(
                                value=curl_postprocess(ENV_API_URL, "summary", ""),
                                language="shell",
                                label="Summarise it",
                            )
                            tag_curl = gr.Code(
                                value=curl_postprocess(ENV_API_URL, "tags", ""),
                                language="shell",
                                label="Tag it",
                            )
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

        # The rail's rows are rendered before these exist, but the render only
        # runs once a browser asks for the page, by which point it can see them.
        detail_outputs = [
            detail_head, detail_job_id, source_box, source_note, detail_status,
            detail_metrics, detail_chat, transcript_group,
            detail_result, result_group,
            actions_group, pp_status, derived_summary, derived_tags,
            detail_raw, detail_raw_acc,
            get_curl, delete_curl, summarize_curl, tag_curl,
        ]
        assert len(detail_outputs) == len(DETAIL_FIELDS), "detail outputs must match DETAIL_FIELDS"

        # -- Wiring ------------------------------------------------------- #
        theme_btn.click(None, None, None, js=THEME_TOGGLE_JS)
        token_box.change(signed_in_html, inputs=[token_box], outputs=[signed_in])
        disconnect_btn.click(
            disconnect,
            outputs=[
                token_box, signed_in, jobs_state, types_state,
                list_status, cursor_state, more_btn, total_state,
            ],
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

        # Your jobs.
        filter_inputs = [type_filter_dd, status_filter_dd, since_filter_box]
        list_inputs = [token_box, api_url_box, types_state, *filter_inputs]
        list_outputs = [jobs_state, types_state, list_status, list_curl, cursor_state, more_btn, total_state]
        refresh_btn.click(list_jobs_view, inputs=list_inputs, outputs=list_outputs)
        more_btn.click(
            load_more_jobs_view,
            inputs=[
                token_box, api_url_box, types_state, jobs_state,
                cursor_state, total_state, *filter_inputs,
            ],
            outputs=list_outputs,
        )
        # Filters are applied by the fetch.
        for control in filter_inputs:
            control.change(list_jobs_view, inputs=list_inputs, outputs=list_outputs)

        pp_outputs = [
            pp_status, derived_summary, derived_tags,
            detail_raw, detail_raw_acc, pairs_state, jobs_state,
        ]
        pp_inputs = [detail_job_id, token_box, api_url_box, pairs_state, jobs_state]
        summarize_btn.click(summarize, inputs=pp_inputs, outputs=pp_outputs)
        tag_btn.click(tag, inputs=pp_inputs, outputs=pp_outputs)

        # Deleting leaves the rail stale, so relist once it has gone through.
        delete_btn.click(
            delete_transcript,
            inputs=[token_box, api_url_box, detail_job_id],
            outputs=[delete_status, delete_raw],
        ).then(list_jobs_view, inputs=list_inputs, outputs=list_outputs)

        # A fresh transcription is not in the rail yet: relist, then open it on
        # the jobs tab, where the two postprocessing buttons live.
        transcribe_pp_btn.click(
            lambda jid: gr.update(selected="jobs") if (jid or "").strip() else gr.update(),
            inputs=[job_id_out],
            outputs=[tabs],
        ).then(list_jobs_view, inputs=list_inputs, outputs=list_outputs).then(
            open_job,
            inputs=[job_id_out, token_box, api_url_box, pairs_state],
            outputs=detail_outputs,
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
