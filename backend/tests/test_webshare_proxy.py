"""Optional Webshare wiring, bounded failures, and credential-safe API errors."""

import logging
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from requests import Response, Session, Timeout
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, ProxyError, RetryError
from youtube_transcript_api import (
    AgeRestricted, IpBlocked, PoTokenRequired, RequestBlocked,
    TranscriptsDisabled, VideoUnavailable, YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import WebshareProxyConfig

from app.main import create_app
from app.schemas.error import ApiException
from app.services import video_service
from app.services import youtube_transcript_service as provider

VIDEO_ID = "dQw4w9WgXcQ"
USERNAME = "test-only-proxy-user"
PASSWORD = "test-only-proxy-password"
SECRET_ERROR = f"http://{USERNAME}:{PASSWORD}@p.webshare.io:80/"
# Capture before the autouse fixture disables network sends. Tests restoring this
# implementation also mock HTTPAdapter.send, so they still cannot use the network.
SESSION_SEND = Session.send


@pytest.fixture
def proxy_credentials(monkeypatch):
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", USERNAME)
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", PASSWORD)


def test_no_credentials_preserves_direct_client(caption_api, monkeypatch):
    constructor = Mock(side_effect=AssertionError("Proxy should not be configured."))
    monkeypatch.setattr(provider, "WebshareProxyConfig", constructor)
    assert provider.fetch_transcript(VIDEO_ID)
    constructor.assert_not_called()
    kwargs = provider.YouTubeTranscriptApi.call_args.kwargs
    assert set(kwargs) == {"http_client"}
    assert kwargs["http_client"].trust_env is True
    assert caption_api.list.call_count == 1


def test_both_credentials_enable_builtin_webshare(
    caption_api, proxy_credentials, monkeypatch, caplog
):
    constructor = Mock(wraps=WebshareProxyConfig)
    monkeypatch.setattr(provider, "WebshareProxyConfig", constructor)
    with caplog.at_level(logging.INFO, logger=provider.__name__):
        result = provider.fetch_transcript(VIDEO_ID)
    constructor.assert_called_once_with(
        proxy_username=USERNAME, proxy_password=PASSWORD, retries_when_blocked=0
    )
    kwargs = provider.YouTubeTranscriptApi.call_args.kwargs
    assert isinstance(kwargs["proxy_config"], WebshareProxyConfig)
    assert kwargs["proxy_config"].retries_when_blocked == 0
    assert kwargs["http_client"].trust_env is False
    assert result[0].start_seconds == 0.25
    assert result[0].end_seconds == 4.75
    assert "transport=webshare" in caplog.text
    assert USERNAME not in caplog.text and PASSWORD not in caplog.text


def test_builtin_config_rotates_and_has_no_hidden_adapter_retries(proxy_credentials):
    config = provider.get_proxy_config()
    with provider.BoundedYouTubeSession(provider.TranscriptSettings()) as session:
        YouTubeTranscriptApi(http_client=session, proxy_config=config)
        assert session.headers["Connection"] == "close"
        for scheme in ("http", "https"):
            parsed = urlsplit(session.proxies[scheme])
            assert parsed.hostname == "p.webshare.io"
            assert parsed.username.endswith("-rotate")
            assert session.adapters[scheme + "://"].max_retries.total == 0


@pytest.mark.parametrize("username,password", [("", ""), ("   ", "\t")])
def test_blank_credentials_use_direct_mode(monkeypatch, caption_api, username, password):
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", username)
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", password)
    provider.fetch_transcript(VIDEO_ID)
    assert "proxy_config" not in provider.YouTubeTranscriptApi.call_args.kwargs


@pytest.mark.parametrize("username,password", [
    (USERNAME, ""), ("", PASSWORD), (USERNAME, "  "), ("\t", PASSWORD),
])
def test_partial_credentials_are_a_safe_configuration_error(
    monkeypatch, caption_api, caplog, username, password
):
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", username)
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", password)
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caught.value.status_code == 500
    assert caught.value.code == "INTERNAL_SERVER_ERROR"
    assert "WEBSHARE_PROXY_USERNAME" in caught.value.message
    assert "WEBSHARE_PROXY_PASSWORD" in caught.value.message
    assert USERNAME not in caught.value.message + caplog.text
    assert PASSWORD not in caught.value.message + caplog.text
    provider.YouTubeTranscriptApi.assert_not_called()


@pytest.mark.parametrize("error,status,code", [
    (RequestBlocked(VIDEO_ID), 503, "YOUTUBE_ACCESS_BLOCKED"),
    (IpBlocked(VIDEO_ID), 429, "YOUTUBE_RATE_LIMITED"),
    (ProxyError(SECRET_ERROR), 502, "TRANSCRIPT_FETCH_FAILED"),
    (ConnectionError(SECRET_ERROR), 502, "TRANSCRIPT_FETCH_FAILED"),
    (RetryError(SECRET_ERROR), 502, "TRANSCRIPT_FETCH_FAILED"),
    (Timeout(SECRET_ERROR), 504, "TRANSCRIPT_FETCH_TIMEOUT"),
    (ApiException(503, "YOUTUBE_ACCESS_BLOCKED", "Blocked."), 503, "YOUTUBE_ACCESS_BLOCKED"),
    (ApiException(429, "YOUTUBE_RATE_LIMITED", "Rate limited."), 429, "YOUTUBE_RATE_LIMITED"),
])
def test_proxy_retry_exhaustion_keeps_safe_existing_errors(
    caption_api, proxy_credentials, caplog, error, status, code
):
    caption_api.list.side_effect = error
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert caption_api.list.call_count == 2
    # One API instance: no implicit direct fallback or fresh retry budget.
    provider.YouTubeTranscriptApi.assert_called_once()
    assert caught.value.status_code == status
    assert caught.value.code == code
    assert USERNAME not in caught.value.message + caplog.text
    assert PASSWORD not in caught.value.message + caplog.text
    assert SECRET_ERROR not in caught.value.message + caplog.text


@pytest.mark.parametrize("error", [
    RequestBlocked(VIDEO_ID), IpBlocked(VIDEO_ID), ProxyError(SECRET_ERROR),
    Timeout(SECRET_ERROR), RetryError(SECRET_ERROR),
])
def test_one_proxy_retry_can_succeed(caption_api, proxy_credentials, error):
    tracks = caption_api.list.return_value
    caption_api.list.side_effect = [error, tracks]
    assert provider.fetch_transcript(VIDEO_ID)[0].text == "Caption fixture: first sentence."
    assert caption_api.list.call_count == 2


def test_failure_while_fetching_caption_track_can_retry(caption_api, proxy_credentials):
    track = caption_api.list.return_value[0]
    original = track.fetch.return_value
    track.fetch.side_effect = [Timeout(SECRET_ERROR), original]
    assert provider.fetch_transcript(VIDEO_ID)[0].end_seconds == 4.75
    assert track.fetch.call_count == 2
    assert caption_api.list.call_count == 2


@pytest.mark.parametrize("error", [
    TranscriptsDisabled(VIDEO_ID), VideoUnavailable(VIDEO_ID), AgeRestricted(VIDEO_ID),
    PoTokenRequired(VIDEO_ID), ValueError(SECRET_ERROR),
])
def test_permanent_caption_errors_are_not_retried(caption_api, proxy_credentials, error):
    caption_api.list.side_effect = error
    with pytest.raises(ApiException):
        provider.fetch_transcript(VIDEO_ID)
    assert caption_api.list.call_count == 1


@pytest.mark.parametrize("exhausted", ["time", "sends"])
def test_proxy_retry_cannot_reset_existing_limits(caption_api, proxy_credentials, exhausted):
    def fail(video_id):
        session = provider.YouTubeTranscriptApi.call_args.kwargs["http_client"]
        if exhausted == "time":
            session.deadline = 0
        else:
            session.send_count = 6
        raise RequestBlocked(video_id)

    caption_api.list.side_effect = fail
    with pytest.raises(ApiException):
        provider.fetch_transcript(VIDEO_ID)
    assert caption_api.list.call_count == 1


@pytest.mark.parametrize("http_status,expected_status,code", [
    (403, 503, "YOUTUBE_ACCESS_BLOCKED"), (429, 429, "YOUTUBE_RATE_LIMITED"),
])
def test_proxy_retries_obey_http_send_limits_and_timeouts(
    monkeypatch, make_track, proxy_credentials, http_status, expected_status, code
):
    sends = []
    sessions = []

    def adapter_send(self, request, **kwargs):
        sends.append(kwargs["timeout"])
        assert self.max_retries.total == 0
        assert request.headers["Connection"] == "close"
        response = Response()
        response.status_code = http_status
        response._content = b""
        response.request = request
        response.url = request.url
        return response

    def client_factory(**kwargs):
        api = YouTubeTranscriptApi(**kwargs)
        session = kwargs["http_client"]
        sessions.append(session)

        def list_tracks(video_id):
            session.get(f"https://www.youtube.com/watch?v={video_id}")
            return [make_track()]

        api.list = Mock(side_effect=list_tracks)
        return api

    monkeypatch.setattr(Session, "send", SESSION_SEND)
    monkeypatch.setattr(HTTPAdapter, "send", adapter_send)
    monkeypatch.setattr(provider, "YouTubeTranscriptApi", client_factory)
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript(VIDEO_ID)
    assert len(sessions) == 1
    assert sessions[0].send_count == len(sends) == 2
    assert all(0 < connect <= 3 and 0 < read <= 10 for connect, read in sends)
    assert caught.value.status_code == expected_status
    assert caught.value.code == code


def test_partial_credentials_use_existing_http_error_envelope(monkeypatch, caption_api):
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", USERNAME)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/api/videos/process", json={
            "url": f"https://youtu.be/{VIDEO_ID}"
        })
    assert response.status_code == 500
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "Configure both" in response.json()["error"]["message"]
    assert USERNAME not in response.text
    caption_api.list.assert_not_called()


@pytest.mark.parametrize("error,status,code", [
    (ProxyError(SECRET_ERROR), 502, "TRANSCRIPT_FETCH_FAILED"),
    (RetryError(SECRET_ERROR), 502, "TRANSCRIPT_FETCH_FAILED"),
    (Timeout(SECRET_ERROR), 504, "TRANSCRIPT_FETCH_TIMEOUT"),
])
def test_proxy_failures_do_not_expose_credentials_or_store_video(
    caption_api, proxy_credentials, caplog, error, status, code
):
    caption_api.list.side_effect = error
    video_service.processed_videos.clear()
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/api/videos/process", json={
            "url": f"https://youtu.be/{VIDEO_ID}"
        })
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert USERNAME not in response.text + caplog.text
    assert PASSWORD not in response.text + caplog.text
    assert SECRET_ERROR not in response.text + caplog.text
    assert video_service.processed_videos == {}
