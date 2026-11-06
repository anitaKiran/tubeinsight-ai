"""Cache-first HTTP processing, confirmed writes, and deployment policy guards."""

import pytest
from fastapi.testclient import TestClient
from requests import Timeout
from youtube_transcript_api import RequestBlocked, TranscriptsDisabled, VideoUnavailable

from app.main import create_app
from app.repositories import video_repository
from app.schemas.error import ApiException
from app.services import ingestion_service, youtube_transcript_service as provider

VIDEO_ID = "dQw4w9WgXcQ"
URL = f"https://youtu.be/{VIDEO_ID}"
DEPLOYMENTS = [
    {"VERCEL": "1"},
    {"VERCEL": "1", "VERCEL_ENV": "preview"},
    {"VERCEL_ENV": "preview"},
    {"VERCEL_ENV": "production"},
    {"VERCEL_ENV": "development"},
    {"APP_ENV": "production"},
    {"APP_ENV": " PROD "},
]


@pytest.fixture
def auto_client(monkeypatch, saved_videos):
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "auto")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


def test_local_miss_extracts_saves_and_returns_existing_contract(auto_client, saved_videos, caption_api):
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "mode", "video", "transcript"}
    assert body["status"] == "ready" and body["mode"] == "real"
    assert body["video"] == {
        "id": VIDEO_ID, "title": None, "duration_seconds": None,
        "url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "thumbnail_url": f"https://img.youtube.com/vi/{VIDEO_ID}/hqdefault.jpg",
    }
    assert body["transcript"] == saved_videos[VIDEO_ID].model_dump()["transcript"]
    assert body["transcript"][0]["start_seconds"] == .25
    assert body["transcript"][0]["end_seconds"] == 4.75
    assert body["transcript"][1]["start_seconds"] == 4.0  # Keep overlap.
    assert saved_videos[VIDEO_ID].language == "en"
    caption_api.list.assert_called_once_with(VIDEO_ID)
    video_repository.upsert_video.assert_called_once()


def test_repeated_requests_use_persistent_cache(auto_client, saved_videos, caption_api):
    first = auto_client.post("/api/videos/process", json={"url": URL})
    second = auto_client.post("/api/videos/process", json={"url": f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    caption_api.list.assert_called_once()
    video_repository.upsert_video.assert_called_once()


def test_cached_metadata_is_preserved(auto_client, saved_videos, make_record, caption_api):
    saved_videos[VIDEO_ID] = make_record(title="Existing title", duration_seconds=123, language="fr", thumbnail_url="https://example.com/thumb.jpg")
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.json()["video"]["title"] == "Existing title"
    assert response.json()["video"]["duration_seconds"] == 123
    assert response.json()["video"]["thumbnail_url"] == "https://example.com/thumb.jpg"
    assert saved_videos[VIDEO_ID].language == "fr"
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


def test_original_fallback_language_is_saved(auto_client, saved_videos, caption_api, make_track):
    caption_api.list.return_value = [make_track(language="de", generated=True)]
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 200
    assert saved_videos[VIDEO_ID].language == "de"


def test_write_failure_returns_error_instead_of_unsaved_success(auto_client, saved_videos, caption_api):
    def fail(record):
        caption_api.list.assert_called_once()
        assert record.transcript and record.language == "en"
        raise ApiException(503, "DATABASE_UNAVAILABLE", "Transcript storage is unavailable. Try again later.")

    video_repository.upsert_video.side_effect = fail
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert saved_videos == {}


def test_read_failure_does_not_trigger_extraction(auto_client, saved_videos, caption_api):
    video_repository.get_video.side_effect = ApiException(503, "DATABASE_UNAVAILABLE", "Unavailable.")
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 503
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


@pytest.mark.parametrize("error,status,code", [
    (Timeout("private upstream details"), 504, "TRANSCRIPT_FETCH_TIMEOUT"),
    (RequestBlocked(VIDEO_ID), 503, "YOUTUBE_ACCESS_BLOCKED"),
    (TranscriptsDisabled(VIDEO_ID), 404, "TRANSCRIPT_NOT_AVAILABLE"),
    (VideoUnavailable(VIDEO_ID), 404, "VIDEO_UNAVAILABLE"),
])
def test_upstream_errors_preserve_envelope_and_never_save(auto_client, saved_videos, caption_api, error, status, code):
    caption_api.list.side_effect = error
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == code
    assert "private upstream details" not in response.text
    assert not saved_videos
    video_repository.upsert_video.assert_not_called()


def test_empty_transcript_never_saves(auto_client, saved_videos, caption_api, make_track):
    caption_api.list.return_value = [make_track(snippets=[])]
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_AVAILABLE"
    video_repository.upsert_video.assert_not_called()


def test_invalid_provider_result_is_validated_before_saving(auto_client, saved_videos, monkeypatch):
    monkeypatch.setattr(provider, "fetch_transcript_data", lambda _: provider.CaptionTranscript([], "en"))
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    video_repository.upsert_video.assert_not_called()


def test_invalid_url_never_reaches_storage_or_youtube(auto_client, saved_videos, caption_api):
    response = auto_client.post("/api/videos/process", json={"url": "https://evil.example/watch?v=" + VIDEO_ID})
    assert response.status_code == 400
    video_repository.get_video.assert_not_called()
    caption_api.list.assert_not_called()


@pytest.mark.parametrize("cached", [False, True])
def test_explicit_local_supabase_mode_never_fetches(auto_client, saved_videos, make_record, caption_api, monkeypatch, cached):
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "supabase")
    if cached:
        saved_videos[VIDEO_ID] = make_record()
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == (200 if cached else 404)
    if not cached:
        assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_CACHED"
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


@pytest.mark.parametrize("deployment", DEPLOYMENTS)
@pytest.mark.parametrize("cached", [False, True])
def test_deployment_overrides_auto_mode(auto_client, saved_videos, make_record, caption_api, monkeypatch, deployment, cached):
    for key, value in deployment.items():
        monkeypatch.setenv(key, value)
    if cached:
        saved_videos[VIDEO_ID] = make_record()
    response = auto_client.post("/api/videos/process", json={"url": URL})
    assert response.status_code == (200 if cached else 404)
    if not cached:
        assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_CACHED"
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


@pytest.mark.parametrize("deployment", DEPLOYMENTS)
def test_provider_and_cli_also_refuse_deployment_extraction(monkeypatch, saved_videos, caption_api, deployment):
    for key, value in deployment.items():
        monkeypatch.setenv(key, value)
    for operation in [lambda: provider.fetch_transcript_data(VIDEO_ID), lambda: ingestion_service.ingest_video(URL)]:
        with pytest.raises(ApiException) as caught:
            operation()
        assert caught.value.code == "CONFIGURATION_ERROR"
    provider.YouTubeTranscriptApi.assert_not_called()
    video_repository.get_video.assert_not_called()
