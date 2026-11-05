"""tubeInsight-ai caption provider using youtube-transcript-api's public API."""

import logging
import math
import os
import re
import time
from dataclasses import dataclass

from requests import HTTPError, RequestException, Session, Timeout
from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    Transcript,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)

from app.runtime import require_local_extraction
from app.schemas.error import ApiException
from app.schemas.video import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptSettings:
    languages: tuple[str, ...] = ("en",)
    allow_language_fallback: bool = True
    connect_timeout: float = 3.0
    read_timeout: float = 10.0
    request_budget: float = 30.0

    @classmethod
    def from_env(cls) -> "TranscriptSettings":
        languages = tuple(
            code.strip() for code in os.getenv("YOUTUBE_CAPTION_LANGUAGES", "en").split(",")
            if code.strip()
        )
        if not languages or any(
            re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", code) is None
            for code in languages
        ):
            raise ValueError("YOUTUBE_CAPTION_LANGUAGES must contain language codes.")
        fallback = os.getenv("YOUTUBE_CAPTION_FALLBACK", "true").lower().strip()
        if fallback not in {"true", "false"}:
            raise ValueError("YOUTUBE_CAPTION_FALLBACK must be true or false.")

        def timeout(name: str, default: str) -> float:
            value = float(os.getenv(name, default))
            if not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError(f"{name} must be greater than 0 and at most 120.")
            return value

        return cls(
            languages=languages,
            allow_language_fallback=fallback == "true",
            connect_timeout=timeout("YOUTUBE_CONNECT_TIMEOUT_SECONDS", "3"),
            read_timeout=timeout("YOUTUBE_READ_TIMEOUT_SECONDS", "10"),
            request_budget=timeout("YOUTUBE_REQUEST_BUDGET_SECONDS", "30"),
        )


class BoundedYouTubeSession(Session):
    """Per-extraction session with bounded sends, redirects, and socket waits."""

    def __init__(self, settings: TranscriptSettings) -> None:
        super().__init__()
        # Direct connections only; ignore ambient proxy and netrc configuration.
        self.trust_env = False
        self.settings = settings
        self.deadline = time.monotonic() + settings.request_budget
        self.send_count = 0
        self.max_redirects = 3

    def send(self, request, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Timeout("Caption request budget exhausted.")
        self.send_count += 1
        if self.send_count > 6:
            raise RequestException("Caption HTTP request limit exceeded.")
        kwargs["timeout"] = (
            min(self.settings.connect_timeout, remaining),
            min(self.settings.read_timeout, remaining),
        )
        # requests' default adapter has no retries. Check status before the
        # library wraps HTTPError and loses access to the response status code.
        response = super().send(request, **kwargs)
        if response.status_code == 429:
            raise ApiException(
                429, "YOUTUBE_RATE_LIMITED",
                "YouTube is rate limiting caption requests. Try again later.",
            )
        if response.status_code == 403:
            raise ApiException(
                503, "YOUTUBE_ACCESS_BLOCKED",
                "YouTube is blocking caption requests from this server.",
            )
        return response


def select_transcript(
    tracks: list[Transcript], settings: TranscriptSettings
) -> Transcript:
    """Language preference takes priority over manual vs automatic captions."""
    for preferred in settings.languages:
        code = preferred.lower()
        matching = [
            track for track in tracks
            if track.language_code.lower() == code
            or track.language_code.lower().startswith(code + "-")
        ]
        if matching:
            return min(matching, key=lambda track: (
                track.is_generated, track.language_code.lower() != code
            ))
    if tracks and settings.allow_language_fallback:
        return min(tracks, key=lambda track: track.is_generated)
    raise ApiException(
        404, "TRANSCRIPT_NOT_AVAILABLE",
        "No transcript is available in an allowed caption language.",
    )


def normalize_snippets(snippets) -> list[TranscriptSegment]:
    """Retain caption order, text, gaps, and overlaps; end = start + duration."""
    segments = []
    for snippet in snippets:
        values = (snippet.start, snippet.duration)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 for value in values
        ):
            raise ValueError("Invalid upstream caption timestamp.")
        end = snippet.start + snippet.duration
        if not math.isfinite(end):
            raise ValueError("Invalid upstream caption end timestamp.")
        segments.append(TranscriptSegment(
            start_seconds=float(snippet.start), end_seconds=float(end), text=snippet.text
        ))
    if not segments or not any(segment.text.strip() for segment in segments):
        raise ApiException(
            404, "TRANSCRIPT_NOT_AVAILABLE",
            "No transcript is available for this video.",
        )
    return segments


def _retrieve_captions(
    api: YouTubeTranscriptApi, video_id: str, settings: TranscriptSettings
) -> tuple[Transcript, list[TranscriptSegment]]:
    tracks = list(api.list(video_id))
    track = select_transcript(tracks, settings)
    return track, normalize_snippets(track.fetch(preserve_formatting=False))


@dataclass(frozen=True)
class CaptionTranscript:
    segments: list[TranscriptSegment]
    language: str


def fetch_transcript_data(video_id: str) -> CaptionTranscript:
    """Fetch one original caption track, without translation or fabricated data."""
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) is None:
        raise ApiException(400, "INVALID_YOUTUBE_URL", "Please provide a valid YouTube URL.")
    require_local_extraction()
    try:
        settings = TranscriptSettings.from_env()
    except ValueError:
        raise ApiException(
            500, "CONFIGURATION_ERROR", "Invalid local YouTube caption settings. Check backend configuration."
        ) from None
    try:
        # The library's Session is not thread-safe; use one direct session per fetch.
        with BoundedYouTubeSession(settings) as session:
            api = YouTubeTranscriptApi(http_client=session)
            track, segments = _retrieve_captions(api, video_id, settings)
            logger.info(
                "Caption extraction succeeded: video=%s language=%s generated=%s",
                video_id, track.language_code, track.is_generated,
            )
            return CaptionTranscript(segments=segments, language=track.language_code)
    except ApiException:
        raise
    except InvalidVideoId:
        raise ApiException(
            400, "INVALID_YOUTUBE_URL",
            "Please provide a valid YouTube URL.",
        ) from None
    except (TranscriptsDisabled, NoTranscriptFound):
        raise ApiException(
            404, "TRANSCRIPT_NOT_AVAILABLE",
            "No transcript is available for this video.",
        ) from None
    except VideoUnavailable:
        raise ApiException(
            404, "VIDEO_UNAVAILABLE",
            "This YouTube video is unavailable.",
        ) from None
    except (AgeRestricted, VideoUnplayable):
        raise ApiException(
            403, "VIDEO_UNAVAILABLE",
            "This YouTube video is private or restricted.",
        ) from None
    except IpBlocked:
        # The library uses this for HTTP 429 and CAPTCHA/IP refusals.
        raise ApiException(
            429, "YOUTUBE_RATE_LIMITED",
            "YouTube is rate limiting caption requests. Try again later.",
        ) from None
    except (RequestBlocked, PoTokenRequired):
        raise ApiException(
            503, "YOUTUBE_ACCESS_BLOCKED",
            "YouTube is blocking caption requests from this server.",
        ) from None
    except Timeout:
        raise ApiException(
            504, "TRANSCRIPT_FETCH_TIMEOUT",
            "YouTube caption retrieval timed out. Try again later.",
        ) from None
    except HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise ApiException(
                429, "YOUTUBE_RATE_LIMITED",
                "YouTube is rate limiting caption requests. Try again later.",
            ) from None
        raise ApiException(
            502, "TRANSCRIPT_FETCH_FAILED",
            "Could not retrieve YouTube captions. Try again later.",
        ) from None
    except Exception as exc:
        # Includes upstream XML/JSON/schema failures. Log only the exception type,
        # never upstream HTML, cookies, signed URLs, or private configuration.
        logger.warning(
            "Caption extraction failed: video=%s type=%s",
            video_id, type(exc).__name__,
        )
        raise ApiException(
            502, "TRANSCRIPT_FETCH_FAILED",
            "Could not retrieve YouTube captions. Try again later.",
        ) from None


def fetch_transcript(video_id: str) -> list[TranscriptSegment]:
    """Compatibility helper for local callers that only need caption segments."""
    return fetch_transcript_data(video_id).segments
