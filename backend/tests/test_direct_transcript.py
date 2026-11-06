"""YouTube extraction uses direct connections, even with legacy proxy variables."""

import pytest
from requests import Request, Response, Session, Timeout
from requests.adapters import HTTPAdapter
from youtube_transcript_api import RequestBlocked

from app.schemas.error import ApiException
from app.services import youtube_transcript_service as provider

VIDEO_ID = "dQw4w9WgXcQ"
SESSION_SEND = Session.send


@pytest.mark.parametrize("username,password", [("obsolete-user", "obsolete-password"), ("obsolete-user", "")])
def test_legacy_credentials_are_ignored(monkeypatch, caption_api, caplog, username, password):
    monkeypatch.setenv("WEBSHARE_PROXY_USERNAME", username)
    monkeypatch.setenv("WEBSHARE_PROXY_PASSWORD", password)
    assert provider.fetch_transcript_data(VIDEO_ID).language == "en"
    kwargs = provider.YouTubeTranscriptApi.call_args.kwargs
    assert set(kwargs) == {"http_client"}
    assert kwargs["http_client"].trust_env is False
    assert not kwargs["http_client"].proxies
    assert "obsolete-user" not in caplog.text and "obsolete-password" not in caplog.text


def test_ambient_proxy_cannot_route_direct_youtube_requests(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://private-user:private-password@invalid.example:8080")
    monkeypatch.setenv("ALL_PROXY", "http://private-user:private-password@invalid.example:8080")
    received = []

    def send(self, request, **kwargs):
        received.append(kwargs)
        response = Response()
        response.status_code = 200
        response._content = b""
        response.request = request
        return response

    monkeypatch.setattr(Session, "send", SESSION_SEND)
    monkeypatch.setattr(HTTPAdapter, "send", send)
    with provider.BoundedYouTubeSession(provider.TranscriptSettings()) as session:
        session.get("https://www.youtube.com/watch?v=" + VIDEO_ID)
        assert received[0]["proxies"] == {}
        assert session.adapters["https://"].max_retries.total == 0


@pytest.mark.parametrize("error", [RequestBlocked(VIDEO_ID), Timeout("private details")])
def test_direct_failures_have_no_proxy_or_implicit_retry(caption_api, error, caplog):
    caption_api.list.side_effect = error
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript_data(VIDEO_ID)
    caption_api.list.assert_called_once()
    assert "private details" not in caplog.text + caught.value.message


def test_invalid_caption_settings_have_a_safe_configuration_error(monkeypatch, caption_api):
    monkeypatch.setenv("YOUTUBE_REQUEST_BUDGET_SECONDS", "private-invalid-value")
    with pytest.raises(ApiException) as caught:
        provider.fetch_transcript_data(VIDEO_ID)
    assert caught.value.code == "CONFIGURATION_ERROR"
    assert "private-invalid-value" not in caught.value.message
    provider.YouTubeTranscriptApi.assert_not_called()
