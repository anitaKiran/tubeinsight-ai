"""Deterministic caption fixtures. Ordinary tests may not use the network."""

from unittest.mock import Mock

import pytest
from requests import Session
from youtube_transcript_api import (
    FetchedTranscript, FetchedTranscriptSnippet, Transcript, YouTubeTranscriptApi,
)

from app.services import youtube_transcript_service


@pytest.fixture(autouse=True)
def isolated_caption_environment(monkeypatch, request):
    if request.node.get_closest_marker("integration"):
        return
    for key, value in {
        "YOUTUBE_CAPTION_LANGUAGES": "en",
        "YOUTUBE_CAPTION_FALLBACK": "true",
        "YOUTUBE_CONNECT_TIMEOUT_SECONDS": "3",
        "YOUTUBE_READ_TIMEOUT_SECONDS": "10",
        "YOUTUBE_REQUEST_BUDGET_SECONDS": "30",
    }.items():
        monkeypatch.setenv(key, value)

    def forbidden_send(*args, **kwargs):
        raise AssertionError("Automated tests must mock external YouTube requests.")

    monkeypatch.setattr(Session, "send", forbidden_send)


@pytest.fixture
def make_track():
    def create(language="en", generated=False, snippets=None):
        if snippets is None:
            snippets = [
                FetchedTranscriptSnippet("Caption fixture: first sentence.", 0.25, 4.5),
                FetchedTranscriptSnippet("Caption fixture: second sentence.", 4.0, 2.125),
            ]
        track = Mock(spec=Transcript)
        track.language_code = language
        track.is_generated = generated
        track.fetch.return_value = FetchedTranscript(
            snippets=snippets, video_id="dQw4w9WgXcQ", language=language,
            language_code=language, is_generated=generated,
        )
        return track
    return create


@pytest.fixture
def caption_api(monkeypatch, make_track):
    client = Mock(spec=YouTubeTranscriptApi)
    client.list.return_value = [make_track()]
    factory = Mock(return_value=client)
    monkeypatch.setattr(youtube_transcript_service, "YouTubeTranscriptApi", factory)
    return client
