from io import BytesIO
import wave
from unittest.mock import Mock

from fastapi.testclient import TestClient
import httpx2
from openai import OpenAI
import pytest

from app.main import create_app
from app.services import audio_service as audio
from app.agent.observability import capture_operations


def wav(silent=False):
    stream = BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes((b"\0\0" if silent else b"\1\2") * 1600)
    return stream.getvalue()


@pytest.fixture
def audio_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-audio-key")
    monkeypatch.setenv("MAX_AUDIO_UPLOAD_MB", "4")
    monkeypatch.setenv("AUDIO_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


def provider(monkeypatch, status=200, body=None, failure=None):
    requests = []
    clients = []
    def respond(request):
        requests.append(request)
        if failure:
            raise failure("simulated transport failure", request=request)
        return httpx2.Response(status, json=body if body is not None else {"text": "¿Cuáles son los temas?", "languages": [{"code": "es"}]})
    def factory(**kwargs):
        assert kwargs["timeout"] == 20 and kwargs["max_retries"] == 0
        client = OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(respond)))
        clients.append(client)
        return client
    monkeypatch.setattr(audio, "OpenAI", factory)
    return requests, clients


def upload(client, content=None, name="recording.wav", mime="audio/wav"):
    return client.post("/api/audio/transcribe", files={"file": (name, wav() if content is None else content, mime)})


def test_real_sdk_multipart_contract_and_no_translation(audio_client, monkeypatch):
    requests, clients = provider(monkeypatch)
    with capture_operations() as events:
        response = upload(audio_client, name="private-name.wav", mime="text/plain")
    assert response.status_code == 200
    assert response.json() == {"text": "¿Cuáles son los temas?", "language": "es", "model": "gpt-transcribe"}
    request = requests[0]
    assert request.url.path == "/v1/audio/transcriptions"
    assert b"gpt-transcribe" in request.content and b"question.wav" in request.content
    assert b"private-name" not in request.content and b"translation" not in request.content
    assert len(requests) == 1 and clients[0].is_closed()
    assert {e["name"] for e in events} == {"audio.request", "audio.transcription"}


@pytest.mark.parametrize("content,name,status,code", [
    (b"", "a.wav", 400, "AUDIO_EMPTY"), (b"hello", "a.txt", 415, "AUDIO_UNSUPPORTED_FORMAT"),
    (b"wrong", "a.webm", 422, "AUDIO_INVALID"), (wav(True), "a.wav", 422, "AUDIO_NO_SPEECH"),
    (wav()[:-100], "a.wav", 422, "AUDIO_INVALID"), (b"ID3"+bytes(100), "a.mp3", 422, "AUDIO_INVALID"),
    (b"\x1a\x45\xdf\xa3webm", "a.webm", 422, "AUDIO_INVALID"),
    (b"x"*4_000_001, "a.wav", 413, "AUDIO_TOO_LARGE"),
])
def test_invalid_uploads_never_call_provider(audio_client, monkeypatch, content, name, status, code):
    factory = Mock()
    monkeypatch.setattr(audio, "OpenAI", factory)
    response = upload(audio_client, content, name)
    assert response.status_code == status and response.json()["error"]["code"] == code
    factory.assert_not_called()


def test_missing_file_shared_error(audio_client):
    response = audio_client.post("/api/audio/transcribe")
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("status,expected,code", [(400,422,"AUDIO_INVALID"), (422,422,"AUDIO_INVALID"),
    (401,503,"AUDIO_UNAVAILABLE"), (403,503,"AUDIO_UNAVAILABLE"), (404,503,"AUDIO_UNAVAILABLE"),
    (429,429,"AUDIO_RATE_LIMITED"), (500,502,"AUDIO_TRANSCRIPTION_FAILED")])
def test_provider_errors_safe_and_not_retried(audio_client, monkeypatch, caplog, status, expected, code):
    calls, _ = provider(monkeypatch, status=status, body={"error": {"message": "secret provider content sk-sensitive"}})
    response = upload(audio_client)
    assert response.status_code == expected and response.json()["error"]["code"] == code
    assert len(calls) == 1 and "sk-sensitive" not in response.text + caplog.text


@pytest.mark.parametrize("failure,status,code", [(httpx2.ReadTimeout,504,"AUDIO_TIMEOUT"), (httpx2.ConnectError,503,"AUDIO_UNAVAILABLE")])
def test_network_failure(audio_client, monkeypatch, failure, status, code):
    calls, _ = provider(monkeypatch, failure=failure)
    response = upload(audio_client)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert len(calls) == 1


@pytest.mark.parametrize("body,expected", [({"text":"  "},None), ({"text":"hello"},None),
    ({"text":"hello","languages":[{"code":"en"},{"code":"es"}]},None)])
def test_no_invented_speech_or_language(audio_client, monkeypatch, body, expected):
    provider(monkeypatch, body=body)
    response = upload(audio_client)
    if not body["text"].strip():
        assert response.status_code == 422 and response.json()["error"]["code"] == "AUDIO_NO_SPEECH"
    else:
        assert response.status_code == 200 and response.json()["language"] is expected


def test_missing_key_and_bad_configuration_safe(audio_client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert upload(audio_client).json()["error"]["code"] == "CONFIGURATION_ERROR"
    monkeypatch.setenv("MAX_AUDIO_UPLOAD_MB", "nan")
    assert upload(audio_client).status_code == 500


def test_configured_lower_size_limit(audio_client, monkeypatch):
    monkeypatch.setenv("MAX_AUDIO_UPLOAD_MB", ".01")
    response = upload(audio_client, b"x"*10001)
    assert response.status_code == 413


def test_upload_closed_on_success_and_provider_failure(audio_client, monkeypatch):
    from starlette.datastructures import UploadFile
    closed = []
    original = UploadFile.close
    async def close(self):
        await original(self)
        closed.append(self.file.closed)
    monkeypatch.setattr(UploadFile, "close", close)
    provider(monkeypatch)
    assert upload(audio_client).status_code == 200
    provider(monkeypatch, status=500)
    assert upload(audio_client).status_code == 502
    assert len(closed) >= 2 and all(closed)


def test_browser_webm_container_gate_then_provider_decode(audio_client, monkeypatch):
    # Structural fixture only. It is deliberately not a measured codec/speech test.
    provider(monkeypatch)
    response = upload(audio_client, b"\x1a\x45\xdf\xa3webmA_OPUS\x1f\x43\xb6\x75payload", "browser.webm", "audio/webm;codecs=opus")
    assert response.status_code == 200


def test_chunked_body_limit_before_parsing(monkeypatch):
    import anyio
    from app.audio_upload import AudioUploadLimitMiddleware
    monkeypatch.setenv("MAX_AUDIO_UPLOAD_MB", ".01")
    called, sent = [], []
    async def downstream(*args):
        called.append(True)
    async def receive():
        return {"type":"http.request", "body": b"x"*40000, "more_body": True}
    async def send(message):
        sent.append(message)
    async def run():
        await AudioUploadLimitMiddleware(downstream)({"type":"http", "path":"/api/audio/transcribe", "method":"POST", "headers":[]}, receive, send)
    anyio.run(run)
    assert not called and sent[0]["status"] == 413


def test_upload_limit_error_keeps_cors(audio_client):
    response = audio_client.post("/api/audio/transcribe", headers={"Content-Length":"5000000", "Origin":"http://localhost:5173"}, content=b"")
    assert response.status_code == 413 and response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_existing_contracts_and_no_evaluation_route(audio_client):
    spec = audio_client.get("/openapi.json").json()
    assert set(spec["paths"]) == {"/api/health", "/api/videos/process", "/api/chat/ask", "/api/audio/transcribe"}
    assert set(spec["components"]["schemas"]["ChatResponse"]["properties"]) == {"video_id", "conversation_id", "mode", "answer", "sources"}
    assert set(spec["components"]["schemas"]["ChatRequest"]["required"]) == {"video_id", "question"}
