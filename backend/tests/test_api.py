"""API contract and frontend integration checks; no external network requests."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import DEFAULT_CORS_ORIGINS, create_app
from app.services import mock_chat_service, mock_video_service

VIDEO_ID = "dQw4w9WgXcQ"
OTHER_VIDEO_ID = "abcdefghijk"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    mock_video_service.processed_videos.clear()
    mock_chat_service.conversations.clear()
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client
    mock_video_service.processed_videos.clear()
    mock_chat_service.conversations.clear()


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]


def process(client, video_id=VIDEO_ID):
    response = client.post(
        "/api/videos/process", json={"url": f"https://youtu.be/{video_id}"}
    )
    assert response.status_code == 200
    return response.json()


def ask(client, **overrides):
    payload = {"video_id": VIDEO_ID, "question": "What is this video about?"}
    payload.update(overrides)
    return client.post("/api/chat/ask", json=payload)


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "service": "videowise-api", "mode": "mock"
    }


@pytest.mark.parametrize("url", [
    VIDEO_URL,
    f"https://youtube.com/watch?v={VIDEO_ID}&t=42s",
    f"https://m.youtube.com/watch?feature=share&v={VIDEO_ID}",
    f"https://youtu.be/{VIDEO_ID}?si=share-token",
    f"https://www.youtu.be/{VIDEO_ID}/",
    f"https://www.youtube.com/shorts/{VIDEO_ID}",
    f"https://youtube.com/shorts/{VIDEO_ID}/?feature=share",
    f"https://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}#t=12",
    f"http://youtube.com/watch?v={VIDEO_ID}",
])
def test_supported_video_urls(client, url):
    response = client.post("/api/videos/process", json={"url": url})
    assert response.status_code == 200
    assert response.json()["video"] == {
        "id": VIDEO_ID,
        "title": "VideoWise AI Demo Video",
        "url": VIDEO_URL,
        "thumbnail_url": f"https://img.youtube.com/vi/{VIDEO_ID}/hqdefault.jpg",
        "duration_seconds": 300,
    }


@pytest.mark.parametrize("url", [
    "", "not a URL", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com@evil.example/watch?v=dQw4w9WgXcQ",
    "https://evil.example@youtube.com/watch?v=dQw4w9WgXcQ",
    "https://user:password@youtube.com/watch?v=dQw4w9WgXcQ",
    "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    "//youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com:443/watch?v=dQw4w9WgXcQ",
    "https://youtube.com:bad/watch?v=dQw4w9WgXcQ",
    "https://[youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch", "https://youtube.com/watch?v=",
    "https://youtube.com/watch?v=short",
    "https://youtube.com/watch?v=dQw4w9WgXcQX",
    "https://youtube.com/watch?v=dQw4w9WgXc!",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&v=abcdefghijk",
    "https://youtu.be/", "https://youtu.be/dQw4w9WgXcQ/extra",
    "https://youtube.com/shorts/", "https://youtube.com/shorts/short",
    "https://youtube.com/embed/dQw4w9WgXcQ",
    "https://you\ntube.com/watch?v=dQw4w9WgXcQ",
    " https://youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_invalid_video_urls(client, url):
    response = client.post("/api/videos/process", json={"url": url})
    assert_error(response, 400, "INVALID_YOUTUBE_URL")
    assert mock_video_service.processed_videos == {}


def test_mock_transcript_is_fixed_and_stored(client):
    first = process(client)
    second = process(client, OTHER_VIDEO_ID)
    assert set(first) == {"status", "mode", "video", "transcript"}
    assert first["status"] == "ready"
    assert first["mode"] == "mock"
    assert first["transcript"] == second["transcript"]
    assert first["transcript"] == [
        {
            "start_seconds": 0.0, "end_seconds": 5.0,
            "text": "Welcome to VideoWise AI. This is a simulated transcript for frontend testing.",
        },
        {
            "start_seconds": 5.0, "end_seconds": 12.0,
            "text": "VideoWise AI will allow users to ask questions about YouTube videos.",
        },
        {
            "start_seconds": 12.0, "end_seconds": 20.0,
            "text": "The application will eventually retrieve relevant transcript sections using RAG.",
        },
    ]
    assert set(mock_video_service.processed_videos) == {VIDEO_ID, OTHER_VIDEO_ID}


def test_chat_creates_conversation_and_returns_transcript_source(client):
    video = process(client)
    response = ask(client, conversation_id=None)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"video_id", "conversation_id", "mode", "answer", "sources"}
    assert body["video_id"] == VIDEO_ID
    assert body["mode"] == "mock"
    assert body["answer"] == mock_chat_service.MOCK_ANSWER
    assert body["sources"] == video["transcript"][:1]
    assert UUID(body["conversation_id"]).version == 4


def test_followup_reuses_conversation_and_stores_history(client):
    process(client)
    first = ask(client).json()
    conversation_id = first["conversation_id"]
    # Processing the same video again must not invalidate its conversations.
    process(client)
    response = ask(client, question="  Tell me more.  ", conversation_id=conversation_id)
    assert response.status_code == 200
    assert response.json()["conversation_id"] == conversation_id
    history = mock_chat_service.conversations[UUID(conversation_id)].history
    assert [turn.question for turn in history] == [
        "What is this video about?", "Tell me more."
    ]
    assert all(turn.answer == mock_chat_service.MOCK_ANSWER for turn in history)


def test_new_chats_have_distinct_conversations(client):
    process(client)
    assert ask(client).json()["conversation_id"] != ask(client).json()["conversation_id"]


def test_unknown_video(client):
    assert_error(ask(client), 404, "VIDEO_NOT_FOUND")
    assert mock_chat_service.conversations == {}


def test_unknown_conversation(client):
    process(client)
    assert_error(ask(client, conversation_id=str(uuid4())), 404, "CONVERSATION_NOT_FOUND")
    assert mock_chat_service.conversations == {}


def test_conversation_cannot_change_video(client):
    process(client)
    process(client, OTHER_VIDEO_ID)
    conversation_id = ask(client).json()["conversation_id"]
    assert_error(
        ask(client, video_id=OTHER_VIDEO_ID, conversation_id=conversation_id),
        404, "CONVERSATION_NOT_FOUND",
    )
    assert len(mock_chat_service.conversations[UUID(conversation_id)].history) == 1


@pytest.mark.parametrize("payload", [{}, {"url": None}, {"url": 123}, {"url": []}])
def test_video_request_validation(client, payload):
    assert_error(client.post("/api/videos/process", json=payload), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize("overrides", [
    {"question": ""}, {"question": " \t\n "}, {"question": None}, {"question": 123},
    {"video_id": "bad"}, {"video_id": None}, {"video_id": 123},
    {"conversation_id": "not-a-uuid"}, {"conversation_id": ""}, {"conversation_id": 123},
])
def test_chat_request_validation(client, overrides):
    process(client)
    assert_error(ask(client, **overrides), 422, "VALIDATION_ERROR")
    assert mock_chat_service.conversations == {}


@pytest.mark.parametrize("payload", [{}, {"video_id": VIDEO_ID}, {"question": "Hello"}])
def test_missing_chat_fields(client, payload):
    assert_error(client.post("/api/chat/ask", json=payload), 422, "VALIDATION_ERROR")


def test_malformed_json(client):
    response = client.post(
        "/api/chat/ask", content="{", headers={"Content-Type": "application/json"}
    )
    assert_error(response, 422, "VALIDATION_ERROR")


def test_unexpected_error_is_generic_and_has_cors(client, monkeypatch):
    def fail(url):
        raise RuntimeError("Private implementation details")

    monkeypatch.setattr(mock_video_service, "process_video", fail)
    response = client.post(
        "/api/videos/process", json={"url": VIDEO_URL},
        headers={"Origin": "http://localhost:5173"},
    )
    assert_error(response, 500, "INTERNAL_SERVER_ERROR")
    assert "Private implementation details" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://localhost:3000"])
def test_cors_allowed_origins_and_preflight(client, origin):
    response = client.options("/api/videos/process", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    response = client.post("/api/videos/process", json={}, headers={"Origin": origin})
    assert_error(response, 422, "VALIDATION_ERROR")
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_disallows_unconfigured_origin(client):
    response = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_environment_override(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://frontend.example")
    with TestClient(create_app()) as custom_client:
        response = custom_client.get(
            "/api/health", headers={"Origin": "https://frontend.example"}
        )
        assert response.headers["access-control-allow-origin"] == "https://frontend.example"
        response = custom_client.get(
            "/api/health", headers={"Origin": "http://localhost:5173"}
        )
        assert "access-control-allow-origin" not in response.headers


def test_cors_defaults(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setattr("app.main.load_dotenv", lambda *args: None)
    with TestClient(create_app()) as default_client:
        response = default_client.get(
            "/api/health", headers={"Origin": "http://localhost:5173"}
        )
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "https://example.com/path"])
def test_cors_rejects_wildcards_and_paths(monkeypatch, origin):
    monkeypatch.setenv("CORS_ORIGINS", origin)
    with pytest.raises(ValueError, match="exact HTTP"):
        create_app()


def test_swagger_and_openapi_contract(client):
    assert client.get("/docs").status_code == 200
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["paths"]) == {"/api/health", "/api/videos/process", "/api/chat/ask"}
    for path in ("/api/videos/process", "/api/chat/ask"):
        errors = schema["paths"][path]["post"]["responses"]
        for status in ("422", "500"):
            assert errors[status]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    chat_errors = schema["paths"]["/api/chat/ask"]["post"]["responses"]["404"]
    assert "CONVERSATION_NOT_FOUND" in chat_errors["content"]["application/json"]["examples"]
    models = schema["components"]["schemas"]
    for field in ("title", "duration_seconds"):
        assert {"type": "null"} in models["VideoMetadata"]["properties"][field]["anyOf"]
    assert {"SourceSegment", "TranscriptSegment", "ApiError", "ErrorResponse"} <= set(models)


@pytest.mark.parametrize("method,path,status,code", [
    ("get", "/api/missing", 404, "NOT_FOUND"),
    ("get", "/api/videos/process", 405, "METHOD_NOT_ALLOWED"),
])
def test_routing_errors_use_envelope(client, method, path, status, code):
    assert_error(getattr(client, method)(path), status, code)
