"""Provider normalization, language choice, upstream errors, and network bounds."""

from unittest.mock import Mock

import pytest
from requests import ConnectionError, HTTPError, Request, RequestException, Response, Session, Timeout
from youtube_transcript_api import (
    AgeRestricted, FetchedTranscriptSnippet, InvalidVideoId, IpBlocked,
    NoTranscriptFound, PoTokenRequired, RequestBlocked, TranscriptsDisabled,
    VideoUnavailable, VideoUnplayable, YouTubeDataUnparsable, YouTubeRequestFailed,
)

from app.schemas.error import ApiException
from app.services import youtube_transcript_service as provider

VIDEO_ID = "dQw4w9WgXcQ"


def test_language_priority_beats_manual_foreign_track(caption_api, make_track):
    german = make_track("de")
    english = make_track("en", generated=True)
    caption_api.list.return_value = [german, english]
    segments = provider.fetch_transcript(VIDEO_ID)
    caption_api.list.assert_called_once_with(VIDEO_ID)
    english.fetch.assert_called_once_with(preserve_formatting=False)
    german.fetch.assert_not_called()
    english.translate.assert_not_called()
    assert segments[0].start_seconds == 0.25
    assert segments[0].end_seconds == 4.75
    # Overlapping captions must not be clamped or retimed.
    assert segments[1].start_seconds == 4.0


def test_manual_captions_preferred_in_same_language(caption_api, make_track):
    auto = make_track("en", generated=True)
    manual = make_track("en")
    caption_api.list.return_value = [auto, manual]
    provider.fetch_transcript(VIDEO_ID)
    manual.fetch.assert_called_once()
    auto.fetch.assert_not_called()


def test_regional_english_captions(caption_api, make_track):
    english = make_track("en-US", generated=True)
    caption_api.list.return_value = [make_track("de"), english]
    provider.fetch_transcript(VIDEO_ID)
    english.fetch.assert_called_once()


def test_configured_language_order(caption_api, make_track, monkeypatch):
    monkeypatch.setenv("YOUTUBE_CAPTION_LANGUAGES", "fr,en")
    french = make_track("fr", generated=True)
    caption_api.list.return_value = [make_track("en"), french]
    provider.fetch_transcript(VIDEO_ID)
    french.fetch.assert_called_once()


def test_fallback_preserves_original_text_and_language(caption_api, make_track):
    snippets = [FetchedTranscriptSnippet("Grüße! 日本語の字幕。", 1.2, 0.8)]
    track = make_track("de", snippets=snippets)
    caption_api.list.return_value = [track]
    result = provider.fetch_transcript(VIDEO_ID)
    assert result[0].text == "Grüße! 日本語の字幕。"
    assert result[0].end_seconds == 2.0
    track.translate.assert_not_called()


def test_language_fallback_can_be_disabled(caption_api, make_track, monkeypatch):
    monkeypatch.setenv("YOUTUBE_CAPTION_FALLBACK", "false")
    foreign = make_track("de")
    caption_api.list.return_value = [foreign]
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.code == "TRANSCRIPT_NOT_AVAILABLE"
    foreign.fetch.assert_not_called()


@pytest.mark.parametrize("snippets", [[], [FetchedTranscriptSnippet(" \n ", 0.0, 1.0)]])
def test_empty_captions_are_not_ready(caption_api, make_track, snippets):
    caption_api.list.return_value = [make_track(snippets=snippets)]
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.status_code == 404
    assert caught.value.code == "TRANSCRIPT_NOT_AVAILABLE"


def test_no_caption_tracks(caption_api):
    caption_api.list.return_value = []
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.code == "TRANSCRIPT_NOT_AVAILABLE"


@pytest.mark.parametrize("start,duration,text", [
    (-1.0, 1.0, "caption"), (0.0, -1.0, "caption"),
    (float("nan"), 1.0, "caption"), (0.0, float("inf"), "caption"),
    (1e308, 1e308, "caption"), (True, 1.0, "caption"),
    ("0", 1.0, "caption"), (None, 1.0, "caption"), (0.0, 1.0, None),
])
def test_malformed_upstream_snippets(caption_api, make_track, start, duration, text):
    track = make_track(snippets=[FetchedTranscriptSnippet(text, start, duration)])
    caption_api.list.return_value = [track]
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.status_code == 502
    assert caught.value.code == "TRANSCRIPT_FETCH_FAILED"


@pytest.mark.parametrize("error,status,code", [
    (TranscriptsDisabled(VIDEO_ID), 404, "TRANSCRIPT_NOT_AVAILABLE"),
    (NoTranscriptFound(VIDEO_ID, ["en"], []), 404, "TRANSCRIPT_NOT_AVAILABLE"),
    (VideoUnavailable(VIDEO_ID), 404, "VIDEO_UNAVAILABLE"),
    (VideoUnplayable(VIDEO_ID, "private", []), 403, "VIDEO_UNAVAILABLE"),
    (AgeRestricted(VIDEO_ID), 403, "VIDEO_UNAVAILABLE"),
    (IpBlocked(VIDEO_ID), 429, "YOUTUBE_RATE_LIMITED"),
    (RequestBlocked(VIDEO_ID), 503, "YOUTUBE_ACCESS_BLOCKED"),
    (PoTokenRequired(VIDEO_ID), 503, "YOUTUBE_ACCESS_BLOCKED"),
    (Timeout("secret timeout details"), 504, "TRANSCRIPT_FETCH_TIMEOUT"),
    (ConnectionError("secret connection details"), 502, "TRANSCRIPT_FETCH_FAILED"),
    (YouTubeDataUnparsable(VIDEO_ID), 502, "TRANSCRIPT_FETCH_FAILED"),
    (YouTubeRequestFailed(VIDEO_ID, HTTPError("secret")), 502, "TRANSCRIPT_FETCH_FAILED"),
    (ValueError("secret malformed XML"), 502, "TRANSCRIPT_FETCH_FAILED"),
    (InvalidVideoId(VIDEO_ID), 400, "INVALID_YOUTUBE_URL"),
])
def test_upstream_error_mapping(caption_api, error, status, code):
    caption_api.list.side_effect = error
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.status_code == status
    assert caught.value.code == code
    assert "secret" not in caught.value.message


def test_error_during_caption_fetch_is_mapped(caption_api, make_track):
    track = make_track()
    track.fetch.side_effect = Timeout("private details")
    caption_api.list.return_value = [track]
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.code == "TRANSCRIPT_FETCH_TIMEOUT"


def test_invalid_id_never_calls_youtube(caption_api):
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript("malformed")
    assert caught.value.code == "INVALID_YOUTUBE_URL"
    caption_api.list.assert_not_called()


@pytest.mark.parametrize("name,value", [
    ("YOUTUBE_CONNECT_TIMEOUT_SECONDS", "0"),
    ("YOUTUBE_READ_TIMEOUT_SECONDS", "nan"),
    ("YOUTUBE_REQUEST_BUDGET_SECONDS", "121"),
    ("YOUTUBE_CAPTION_LANGUAGES", ""),
    ("YOUTUBE_CAPTION_LANGUAGES", "../en"),
    ("YOUTUBE_CAPTION_FALLBACK", "maybe"),
])
def test_bad_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        provider.TranscriptSettings.from_env()


def test_session_applies_timeouts_and_closes(monkeypatch, caption_api):
    closed = Mock()
    monkeypatch.setattr(provider.BoundedYouTubeSession, "close", closed)
    provider.fetch_transcript(VIDEO_ID)
    closed.assert_called_once()


def test_session_closes_on_failure(monkeypatch, caption_api):
    closed = Mock()
    monkeypatch.setattr(provider.BoundedYouTubeSession, "close", closed)
    caption_api.list.side_effect = RequestBlocked(VIDEO_ID)
    with pytest.raises(ApiException):
        provider.fetch_transcript(VIDEO_ID)
    closed.assert_called_once()


def test_each_http_send_has_timeout_and_no_retries(monkeypatch):
    received = []

    def send(self, request, **kwargs):
        received.append(kwargs["timeout"])
        response = Response()
        response.status_code = 200
        return response

    monkeypatch.setattr(Session, "send", send)
    with provider.BoundedYouTubeSession(provider.TranscriptSettings()) as session:
        session.send(Request("GET", "https://www.youtube.com").prepare())
        assert 0 < received[0][0] <= 3.0
        assert 0 < received[0][1] <= 10.0
        assert session.max_redirects == 3
        assert session.adapters["https://"].max_retries.total == 0
        for _ in range(5):
            session.send(Request("GET", "https://www.youtube.com").prepare())
        with pytest.raises(RequestException, match="limit"):
            session.send(Request("GET", "https://www.youtube.com").prepare())


def test_request_budget_stops_new_requests(monkeypatch):
    with provider.BoundedYouTubeSession(provider.TranscriptSettings()) as session:
        session.deadline = 0
        with pytest.raises(Timeout):
            session.send(Request("GET", "https://www.youtube.com").prepare())


@pytest.mark.parametrize("status,code", [(429, "YOUTUBE_RATE_LIMITED"), (403, "YOUTUBE_ACCESS_BLOCKED")])
def test_raw_http_status_preserved(monkeypatch, status, code):
    response = Response()
    response.status_code = status
    monkeypatch.setattr(Session, "send", lambda *args, **kwargs: response)
    with provider.BoundedYouTubeSession(provider.TranscriptSettings()) as session:
        with pytest.raises(ApiException) as caught:
            session.send(Request("GET", "https://www.youtube.com").prepare())
    assert caught.value.code == code
