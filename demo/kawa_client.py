"""Reference client for the Makimoto Kawa transcription API.

Dependency-light (only ``requests``) and fully typed: copy this single file
straight into your own project. Read it top to bottom to learn the HTTP
contract: authenticate, list jobs, submit a recording, poll until done, read
the transcript.

    GET    /v1/transcriptions            -> list jobs
    POST   /v1/transcriptions            -> submit audio (multipart), returns job_id
    GET    /v1/transcriptions/{job_id}   -> job status + result when succeeded
    DELETE /v1/transcriptions/{job_id}   -> remove a job (where supported)
    POST   /v1/summarize                 -> summarise a finished transcription
    POST   /v1/tag                       -> tag a finished transcription

Authenticate every request with an API key, created from the dashboard:

    Authorization: Bearer <makimoto_api_key>

Example
-------
>>> client = KawaClient(key="<api-key-from-dashboard>")
>>> job = client.create_transcription("call.mp3", language="en")
>>> *_, final = client.poll(job.job_id)
>>> if final.status == "succeeded":
...     print(final.result.full_text)

Summarising or tagging works the same way, except the input is a transcription
that has already succeeded rather than audio. The POST returns a *new* job id,
and that is the one to poll:

>>> summary_job = client.create_summary(final.job_id)
>>> *_, done = client.poll(summary_job.job_id)
>>> print(done.summary.summary)
"""

from __future__ import annotations

import json
import mimetypes
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

DEFAULT_API_URL = "https://api.makimoto.ai"
TERMINAL_STATUSES = {"succeeded", "failed"}

# The postprocessing dimensions, keyed by the job ``type`` the API gives back,
# so one lookup covers both the request path and the response it produces.
POSTPROCESSING_PATHS = {"summary": "/v1/summarize", "tags": "/v1/tag"}


class KawaError(RuntimeError):
    """Raised when the API returns a non-2xx response.

    ``status_code``, ``body`` and ``headers`` are kept so callers can branch on,
    for example, a 401 (key missing/expired) versus a 404 (unknown job), and
    inspect response headers (such as ``Retry-After`` on a 429, or the ``Server``
    header that reveals whether a 413 came from the API or a proxy in front of it).
    """

    def __init__(self, status_code: int, body: Any, url: str, headers: dict[str, str] | None = None):
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
    def from_dict(cls, raw: dict[str, Any]) -> Segment:
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

    language: str | None
    duration_seconds: float | None
    words_count: int | None
    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TranscriptResult:
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


@dataclass(frozen=True)
class SummaryResult:
    """The ``result`` payload of a succeeded ``summary`` job."""

    topic: str | None
    summary: str
    meta_data: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SummaryResult:
        meta = raw.get("meta_data")
        return cls(
            topic=raw.get("topic"),
            summary=str(raw.get("summary") or ""),
            meta_data=meta if isinstance(meta, dict) else None,
        )


@dataclass(frozen=True)
class TagsResult:
    """The ``result`` payload of a succeeded ``tags`` job.

    ``tags`` maps a lower_snake_case category (``call_reason``,
    ``customer_sentiment``, …) to the values the model selected from it. The
    taxonomy is fixed by the service, not configurable per account.
    """

    tags: dict[str, list[str]] = field(default_factory=dict)
    meta_data: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TagsResult:
        source = raw.get("tags")
        tags: dict[str, list[str]] = {}
        if isinstance(source, dict):
            for category, values in source.items():
                if isinstance(values, list):
                    tags[str(category)] = [str(v) for v in values]
                elif values is not None:  # tolerate a bare string
                    tags[str(category)] = [str(values)]
        meta = raw.get("meta_data")
        return cls(tags=tags, meta_data=meta if isinstance(meta, dict) else None)


@dataclass
class Job:
    """A job, in whatever state the API last reported.

    One row type covers all three dimensions: ``type`` says whether ``result``
    holds a transcript, a summary or a tag set, which is why the accessors
    below are typed separately and each return ``None`` for the wrong type.
    """

    job_id: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Job:
        return cls(
            job_id=str(raw.get("job_id") or raw.get("id") or ""),
            status=str(raw.get("status") or "unknown"),
            raw=raw,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def type(self) -> str:
        """``transcription``, ``summary`` or ``tags``.

        Reported by both the list endpoint and the single-job GET; defaults to
        ``transcription`` on a row from a deployment that predates the field.
        """
        return str(self.raw.get("type") or "transcription")

    @property
    def result(self) -> TranscriptResult | None:
        if self.type != "transcription":
            return None
        payload = self.raw.get("result")
        return TranscriptResult.from_dict(payload) if isinstance(payload, dict) else None

    @property
    def source_job_id(self) -> str | None:
        """The transcription a summary or tags job was derived from.

        Returned by ``GET /v1/transcriptions/{job_id}`` for postprocessing jobs
        created once the API began recording the pairing. ``None`` on a
        transcription, on an older job, and against a deployment that predates
        the field.
        """
        value = self.raw.get("source_job_id")
        return str(value) if value else None

    @property
    def summary(self) -> SummaryResult | None:
        if self.type != "summary":
            return None
        payload = self.raw.get("result")
        return SummaryResult.from_dict(payload) if isinstance(payload, dict) else None

    @property
    def tags(self) -> TagsResult | None:
        if self.type != "tags":
            return None
        payload = self.raw.get("result")
        return TagsResult.from_dict(payload) if isinstance(payload, dict) else None

    @property
    def error(self) -> dict[str, Any] | None:
        err = self.raw.get("error")
        return err if isinstance(err, dict) else None


@dataclass(frozen=True)
class JobPage:
    """One page of ``GET /v1/transcriptions``, and the cursor after it."""
    jobs: list[Job]
    next_cursor: str | None = None


class KawaClient:
    """Minimal client for the Makimoto Kawa transcription API.

    Example
    -------
    >>> client = KawaClient(key="<api-key-from-dashboard>")
    >>> job = client.create_transcription("call.mp3", language="en")
    >>> *_, final = client.poll(job.job_id)
    >>> print(final.result.full_text)
    """

    def __init__(
        self,
        key: str,
        api_url: str = DEFAULT_API_URL,
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ):
        self.key = (key or "").strip()
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        # Metadata of the most recent HTTP response, for debugging.
        self.last_status: int | None = None
        self.last_headers: dict[str, str] = {}

    # -- internals ---------------------------------------------------------- #

    def _url(self, path: str) -> str:
        return f"{self.api_url}{path}"

    def _headers(self) -> dict[str, str]:
        if not self.key:
            raise ValueError("A Makimoto API key is required.")
        return {"Authorization": f"Bearer {self.key}"}

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

    def list_transcriptions(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> JobPage:
        """GET /v1/transcriptions - one page of jobs, newest first.

        The endpoint is cursor-paginated: it answers with at most ``limit``
        jobs (the API defaults to 10, and caps at 100).
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        body = self._request("GET", "/v1/transcriptions", params=params or None)
        items = body.get("transcriptions") or body.get("jobs") or body.get("data") or []
        if isinstance(items, dict):
            items = items.get("items", [])
        next_cursor = body.get("next_cursor")
        return JobPage(
            jobs=[Job.from_dict(item) for item in items if isinstance(item, dict)],
            next_cursor=str(next_cursor) if next_cursor else None,
        )

    def count_transcriptions(self, *, page_size: int = 100) -> int:
        """How many jobs the account has, in total."""
        total = 0
        cursor: str | None = None
        while True:
            page = self.list_transcriptions(limit=page_size, cursor=cursor)
            total += len(page.jobs)
            cursor = page.next_cursor
            if not cursor:
                return total

    def list_all_transcriptions(self, *, page_size: int = 100) -> list[Job]:
        """Every job for the account, by walking the pages to the last one."""
        jobs: list[Job] = []
        cursor: str | None = None
        while True:
            page = self.list_transcriptions(limit=page_size, cursor=cursor)
            jobs.extend(page.jobs)
            cursor = page.next_cursor
            if not cursor:
                return jobs

    def create_transcription(
        self,
        file_path: str | Path,
        *,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        """POST /v1/transcriptions - submit a recording as multipart form-data."""
        path = Path(file_path)
        data: dict[str, str] = {}
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

    def delete_transcription(self, job_id: str) -> dict[str, Any]:
        """DELETE /v1/transcriptions/{job_id} - remove a job, where supported."""
        return self._request("DELETE", f"/v1/transcriptions/{job_id}")

    def create_postprocessing(self, dimension: str, transcription_job_id: str) -> Job:
        """POST /v1/summarize or /v1/tag - derive something from a transcript.

        ``dimension`` is ``summary`` or ``tags``. The source must be one of your
        own *transcription* jobs in status ``succeeded``; no audio is uploaded
        and nothing is generated synchronously.

        The reply is ``202`` with a **new** job id. Poll that id, not the
        source transcription's, and record the pairing yourself: neither the
        response nor the job row records which transcription it came from.

        Distinct failures worth branching on, all via ``KawaError``:
        ``409 TRANSCRIPTION_NOT_READY`` (still running, so retry later),
        ``400 NOT_A_TRANSCRIPTION`` (the id is itself a summary or tags job),
        ``422 TRANSCRIPT_EMPTY`` (succeeded, but no speech).
        """
        path = POSTPROCESSING_PATHS.get(dimension)
        if path is None:
            raise ValueError(f"Unknown dimension {dimension!r}; expected one of {sorted(POSTPROCESSING_PATHS)}")
        job_id = (transcription_job_id or "").strip()
        if not job_id:
            raise ValueError("A transcription job id is required.")
        return Job.from_dict(self._request("POST", path, json={"transcription_job_id": job_id}))

    def create_summary(self, transcription_job_id: str) -> Job:
        """POST /v1/summarize - topic and prose summary for a transcription."""
        return self.create_postprocessing("summary", transcription_job_id)

    def create_tags(self, transcription_job_id: str) -> Job:
        """POST /v1/tag - contact-centre tag set for a transcription."""
        return self.create_postprocessing("tags", transcription_job_id)

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
