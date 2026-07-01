"""Reference client for the Makimoto Kawa transcription API.

Dependency-light (only ``requests``) and fully typed: copy this single file
straight into your own project. Read it top to bottom to learn the HTTP
contract: authenticate, list jobs, submit a recording, poll until done, read
the transcript.

    GET    /v1/transcriptions            -> list jobs
    POST   /v1/transcriptions            -> submit audio (multipart), returns job_id
    GET    /v1/transcriptions/{job_id}   -> job status + transcript when succeeded
    DELETE /v1/transcriptions/{job_id}   -> remove a job (where supported)

Authenticate every request with a dashboard token:

    Authorization: Bearer <makimoto_api_token>

Example
-------
>>> client = KawaClient(token="<dashboard-token>")
>>> job = client.create_transcription("call.mp3", language="en")
>>> *_, final = client.poll(job.job_id)
>>> if final.status == "succeeded":
...     print(final.result.full_text)
"""

from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import requests

DEFAULT_API_URL = "https://api.makimoto.ai"
TERMINAL_STATUSES = {"succeeded", "failed"}


class KawaError(RuntimeError):
    """Raised when the API returns a non-2xx response.

    ``status_code``, ``body`` and ``headers`` are kept so callers can branch on,
    for example, a 401 (token missing/expired) versus a 404 (unknown job), and
    inspect response headers (such as ``Retry-After`` on a 429, or the ``Server``
    header that reveals whether a 413 came from the API or a proxy in front of it).
    """

    def __init__(self, status_code: int, body: Any, url: str, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.body = body
        self.url = url
        self.headers = dict(headers or {})
        detail = ""
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or err.get("code") or "")
            else:
                detail = str(body.get("message") or err or "")
        super().__init__(detail or f"HTTP {status_code}")


@dataclass(frozen=True)
class Segment:
    """One speaker-attributed slice of the transcript."""

    text: str
    time_start: float
    time_end: float
    speaker_id: int
    speaker_alias: str

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Segment":
        speaker_id = raw.get("speaker_id")
        return cls(
            text=str(raw.get("text", "")),
            time_start=float(raw.get("time_start") or 0.0),
            time_end=float(raw.get("time_end") or 0.0),
            speaker_id=int(speaker_id) if speaker_id is not None else 0,
            speaker_alias=str(raw.get("speaker_alias") or f"Speaker {speaker_id if speaker_id is not None else 0}"),
        )


@dataclass(frozen=True)
class TranscriptResult:
    """The ``result`` payload returned once a job succeeds."""

    language: Optional[str]
    duration_seconds: Optional[float]
    words_count: Optional[int]
    segments: List[Segment] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TranscriptResult":
        segments = [Segment.from_dict(s) for s in raw.get("transcript", []) if isinstance(s, dict)]
        return cls(
            language=raw.get("language"),
            duration_seconds=raw.get("duration_seconds"),
            words_count=raw.get("words_count"),
            segments=segments,
        )

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()


@dataclass
class Job:
    """A transcription job, in whatever state the API last reported."""

    job_id: str
    status: str
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Job":
        return cls(
            job_id=str(raw.get("job_id") or raw.get("id") or ""),
            status=str(raw.get("status") or "unknown"),
            raw=raw,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def result(self) -> Optional[TranscriptResult]:
        payload = self.raw.get("result")
        return TranscriptResult.from_dict(payload) if isinstance(payload, dict) else None

    @property
    def error(self) -> Optional[Dict[str, Any]]:
        err = self.raw.get("error")
        return err if isinstance(err, dict) else None


class KawaClient:
    """Minimal client for the Makimoto Kawa transcription API.

    Example
    -------
    >>> client = KawaClient(token="<dashboard-token>")
    >>> job = client.create_transcription("call.mp3", language="en")
    >>> *_, final = client.poll(job.job_id)
    >>> print(final.result.full_text)
    """

    def __init__(
        self,
        token: str,
        api_url: str = DEFAULT_API_URL,
        *,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        self.token = (token or "").strip()
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        # Metadata of the most recent HTTP response, for debugging.
        self.last_status: Optional[int] = None
        self.last_headers: Dict[str, str] = {}

    # -- internals ---------------------------------------------------------- #

    def _url(self, path: str) -> str:
        return f"{self.api_url}{path}"

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("A Makimoto API token is required.")
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # Upload streams the file, so allow a longer timeout for POST.
        timeout = kwargs.pop("timeout", self.timeout)
        response = self._session.request(
            method, self._url(path), headers=self._headers(), timeout=timeout, **kwargs
        )
        self.last_status = response.status_code
        self.last_headers = dict(response.headers)
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {"raw": response.text}
        if response.status_code >= 400:
            raise KawaError(response.status_code, body, response.url, headers=response.headers)
        return body

    # -- endpoints ---------------------------------------------------------- #

    def list_transcriptions(self) -> List[Job]:
        """GET /v1/transcriptions - all jobs for the authenticated account."""
        body = self._request("GET", "/v1/transcriptions")
        items = body.get("transcriptions") or body.get("jobs") or body.get("data") or []
        if isinstance(items, dict):
            items = items.get("items", [])
        return [Job.from_dict(item) for item in items if isinstance(item, dict)]

    def create_transcription(
        self,
        file_path: str | Path,
        *,
        language: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """POST /v1/transcriptions - submit a recording as multipart form-data."""
        path = Path(file_path)
        data: Dict[str, str] = {}
        if language:
            data["language"] = language.strip()
        if metadata:
            data["metadata"] = json.dumps(metadata, separators=(",", ":"))
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            body = self._request(
                "POST",
                "/v1/transcriptions",
                files={"file": (path.name, handle, mime)},
                data=data,
                timeout=120.0,
            )
        return Job.from_dict(body)

    def get_transcription(self, job_id: str) -> Job:
        """GET /v1/transcriptions/{job_id} - status, and transcript once done."""
        return Job.from_dict(self._request("GET", f"/v1/transcriptions/{job_id}"))

    def delete_transcription(self, job_id: str) -> Dict[str, Any]:
        """DELETE /v1/transcriptions/{job_id} - remove a job, where supported."""
        return self._request("DELETE", f"/v1/transcriptions/{job_id}")

    def poll(
        self,
        job_id: str,
        *,
        interval: float = 2.0,
        max_attempts: int = 60,
    ) -> Iterator[Job]:
        """Yield the job on each poll until it reaches a terminal status.

        Poll ``GET /v1/transcriptions/{job_id}`` every ``interval`` seconds while
        the status is ``queued`` or ``processing``; stop on ``succeeded`` or
        ``failed``. Yielding (rather than blocking) lets a UI show live updates.
        """
        for attempt in range(max_attempts):
            job = self.get_transcription(job_id)
            yield job
            if job.is_terminal:
                return
            if attempt < max_attempts - 1:
                time.sleep(interval)
