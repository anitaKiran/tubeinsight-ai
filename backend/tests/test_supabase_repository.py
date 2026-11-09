"""Official SDK integration over a mocked HTTPS transport, not a real project."""

import json
from unittest.mock import Mock

import httpx
import pytest
from postgrest import APIError
from fastapi.testclient import TestClient

from app.db import supabase_client
from app.main import create_app
from app.repositories import video_repository
from app.schemas.error import ApiException
from app.services import chat_service, youtube_transcript_service

VIDEO_ID = "dQw4w9WgXcQ"
KEY = "sb_secret_test_only_not_a_real_key"
HTTP_CLIENT = httpx.Client


@pytest.fixture
def sdk_store(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-only.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", KEY)
    rows, requests, transports = {}, [], []

    def handle(request):
        requests.append(request)
        assert request.url.host == "test-only.supabase.co"
        assert request.url.path == "/rest/v1/videos"
        assert request.headers["apikey"] == KEY
        assert "authorization" not in request.headers
        assert request.extensions["timeout"]["connect"] <= 3
        assert request.extensions["timeout"]["read"] == 10
        if request.method == "GET":
            video_id = request.url.params["video_id"].removeprefix("eq.")
            body = [rows[video_id]] if video_id in rows else []
        else:
            assert request.method == "POST"
            assert request.url.params["on_conflict"] == "video_id"
            assert "resolution=merge-duplicates" in request.headers["prefer"]
            record = json.loads(request.content)
            assert "created_at" not in record and "updated_at" not in record
            rows[record["video_id"]] = record
            body = [record]
        return httpx.Response(200, json=body)

    def client_factory(**kwargs):
        transport = HTTP_CLIENT(transport=httpx.MockTransport(handle), **kwargs)
        transports.append(transport)
        return transport

    monkeypatch.setattr(supabase_client.httpx, "Client", client_factory)
    return rows, requests, transports


def test_sdk_upsert_and_repeated_retrieval(sdk_store, make_record):
    rows, requests, transports = sdk_store
    record = make_record(language="de")
    saved = video_repository.upsert_video(record)
    assert saved == record
    assert video_repository.get_video(VIDEO_ID) == record
    assert video_repository.get_video(VIDEO_ID) == record
    assert rows[VIDEO_ID]["transcript"] == record.model_dump(mode="json")["transcript"]
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert all(transport.is_closed for transport in transports)


def test_upsert_is_idempotent_and_can_update(sdk_store, make_record):
    rows, _, _ = sdk_store
    video_repository.upsert_video(make_record())
    refreshed = make_record(title="Updated title", language="fr")
    assert video_repository.upsert_video(refreshed).title == "Updated title"
    assert len(rows) == 1
    assert rows[VIDEO_ID]["language"] == "fr"


def test_unknown_video_returns_none(sdk_store):
    assert video_repository.get_video(VIDEO_ID) is None


def test_nullable_thumbnail_and_metadata(sdk_store, make_record):
    rows, _, _ = sdk_store
    record = make_record(thumbnail_url=None)
    rows[VIDEO_ID] = record.model_dump(mode="json")
    assert video_repository.get_video(VIDEO_ID).thumbnail_url is None


@pytest.mark.parametrize("transcript", [
    [], [{"start_seconds": 0, "end_seconds": 1, "text": "  "}],
    [{"start_seconds": 2, "end_seconds": 1, "text": "bad order"}],
    [{"start_seconds": 0, "end_seconds": float("inf"), "text": "infinite"}],
    [{"start_seconds": -1, "end_seconds": 1, "text": "negative"}],
    [{"start_seconds": "0", "end_seconds": 1, "text": "wrong type"}],
])
def test_invalid_data_cannot_overwrite_valid_row(sdk_store, make_record, transcript):
    rows, requests, _ = sdk_store
    original = make_record().model_dump(mode="json")
    rows[VIDEO_ID] = original
    invalid = {**original, "transcript": transcript}
    with pytest.raises(ApiException) as caught:
        video_repository.upsert_video(invalid)
    assert caught.value.code == "VALIDATION_ERROR"
    assert rows[VIDEO_ID] == original
    assert requests == []


def test_mutated_model_is_revalidated(sdk_store, make_record):
    record = make_record()
    record.transcript[0].end_seconds = float("inf")
    with pytest.raises(ApiException) as caught:
        video_repository.upsert_video(record)
    assert caught.value.code == "VALIDATION_ERROR"
    assert sdk_store[1] == []


def test_corrupt_stored_data_is_not_returned_as_ready(sdk_store, make_record):
    rows, _, transports = sdk_store
    rows[VIDEO_ID] = {**make_record().model_dump(mode="json"), "transcript": []}
    with pytest.raises(ApiException) as caught:
        video_repository.get_video(VIDEO_ID)
    assert caught.value.code == "INVALID_STORED_TRANSCRIPT"
    assert all(transport.is_closed for transport in transports)


@pytest.mark.parametrize("name,value", [
    ("SUPABASE_URL", ""), ("SUPABASE_SECRET_KEY", ""),
    ("SUPABASE_URL", "http://test-only.supabase.co"),
    ("SUPABASE_URL", "https://user:secret@test-only.supabase.co"),
    ("SUPABASE_URL", "https://test-only.supabase.co/rest/v1"),
    ("SUPABASE_SECRET_KEY", "sb_publishable_not_a_server_key"),
    ("SUPABASE_SECRET_KEY", "eyJ_legacy_key_is_not_silently_substituted"),
    ("SUPABASE_TIMEOUT_SECONDS", "0"), ("SUPABASE_TIMEOUT_SECONDS", "nan"),
    ("SUPABASE_TIMEOUT_SECONDS", "31"),
])
def test_configuration_errors_are_safe(sdk_store, monkeypatch, name, value, caplog):
    monkeypatch.setenv(name, value)
    with pytest.raises(ApiException) as caught:
        with supabase_client.get_supabase_client():
            pytest.fail("Invalid configuration should not construct a client.")
    assert caught.value.code == "CONFIGURATION_ERROR"
    assert KEY not in caught.value.message + caplog.text
    assert "user:secret" not in caught.value.message + caplog.text
    assert sdk_store[1] == []


def test_sdk_options_disable_auth_persistence_and_retries(sdk_store, monkeypatch):
    original = supabase_client.create_client
    factory = Mock(wraps=original)
    monkeypatch.setattr(supabase_client, "create_client", factory)
    video_repository.get_video(VIDEO_ID)
    options = factory.call_args.kwargs["options"]
    assert options.auto_refresh_token is False
    assert options.persist_session is False
    assert options.postgrest_client_retry is False
    assert options.httpx_client.follow_redirects is False


@pytest.mark.parametrize("failure", [
    httpx.ConnectError(KEY), httpx.ReadTimeout(KEY),
    APIError({"code": "42501", "message": KEY, "details": "private details", "hint": "secret"}),
])
def test_database_failures_never_leak_secrets(sdk_store, monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(httpx.MockTransport, "handle_request", fail)
    with pytest.raises(ApiException) as caught:
        video_repository.get_video(VIDEO_ID)
    assert caught.value.status_code == 503
    assert caught.value.code == "DATABASE_UNAVAILABLE"
    assert KEY not in caught.value.message + caplog.text
    assert "private details" not in caught.value.message + caplog.text
    assert all(client.is_closed for client in sdk_store[2])


def test_fresh_api_instances_read_saved_data_without_youtube(sdk_store, make_record, monkeypatch, chat_memory):
    record = video_repository.upsert_video(make_record())
    forbidden = Mock(side_effect=AssertionError("Production must never fetch YouTube."))
    monkeypatch.setattr(youtube_transcript_service, "fetch_transcript_data", forbidden)
    monkeypatch.setattr(youtube_transcript_service, "fetch_transcript", forbidden)
    monkeypatch.setenv("VERCEL", "1")
    for _ in range(2):
        with TestClient(create_app()) as client:
            response = client.post("/api/videos/process", json={"url": f"https://youtu.be/{VIDEO_ID}"})
            assert response.status_code == 200
            assert response.json()["transcript"] == record.model_dump(mode="json")["transcript"]
            assert response.json()["mode"] == "real"
    from app.schemas.chat import SourceSegment
    monkeypatch.setattr(chat_service, "run_agent", lambda video, question, *args: ("Grounded test answer.", [SourceSegment(**video.transcript[0].model_dump())]))
    try:
        with TestClient(create_app()) as client:
            chat = client.post("/api/chat/ask", json={"video_id": VIDEO_ID, "question": "Hello"})
            assert chat.status_code == 200
            assert chat.json()["mode"] == "real"
    finally:
        pass
    forbidden.assert_not_called()
    assert [r.method for r in sdk_store[1]] == ["POST", "GET", "GET", "GET"]


@pytest.mark.parametrize("source", ["youtube", "direct", "", "mock"])
def test_invalid_source_fails_closed_before_database_or_youtube(sdk_store, monkeypatch, source):
    monkeypatch.setenv("TRANSCRIPT_SOURCE", source)
    with TestClient(create_app()) as client:
        response = client.post("/api/videos/process", json={"url": f"https://youtu.be/{VIDEO_ID}"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONFIGURATION_ERROR"
    assert sdk_store[1] == []


def test_source_defaults_to_supabase(sdk_store, make_record, monkeypatch):
    monkeypatch.setattr("app.services.video_service.ensure_indexed", Mock())
    monkeypatch.delenv("TRANSCRIPT_SOURCE", raising=False)
    video_repository.upsert_video(make_record())
    from app.services.video_service import process_video
    assert process_video(f"https://youtu.be/{VIDEO_ID}").mode == "real"
