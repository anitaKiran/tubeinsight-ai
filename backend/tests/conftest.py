"""Deterministic caption fixtures. Ordinary tests may not use the network."""

from unittest.mock import Mock

import httpx
import pytest
from requests import Session
from youtube_transcript_api import (
    FetchedTranscript, FetchedTranscriptSnippet, Transcript, YouTubeTranscriptApi,
)

from app.services import youtube_transcript_service
from app.repositories import video_repository
from app.schemas.stored_video import StoredVideo
from app.schemas.video import TranscriptSegment


@pytest.fixture(autouse=True)
def isolated_caption_environment(monkeypatch, request):
    if request.node.get_closest_marker("integration"):
        return
    # Empty values prevent load_dotenv from reintroducing private configuration.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    for key in ["OPENAI_API_KEY", "PINECONE_API_KEY"]:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-6-luna")
    monkeypatch.setenv("PINECONE_EMBEDDING_MODEL", "llama-text-embed-v2")
    monkeypatch.setenv("PINECONE_EMBEDDING_FIELD", "chunk_text")
    monkeypatch.setenv("PINECONE_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "tubeinsight-chunks")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "")
    monkeypatch.setenv("SUPABASE_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "supabase")
    monkeypatch.setenv("VERCEL", "")
    monkeypatch.setenv("VERCEL_ENV", "")
    monkeypatch.setenv("APP_ENV", "development")
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
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_send)
    import httpx2
    import urllib3
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", forbidden_send)
    monkeypatch.setattr(urllib3.PoolManager, "request", forbidden_send)


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


@pytest.fixture
def make_record():
    def create(video_id="dQw4w9WgXcQ", **overrides):
        values = {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "language": "en",
            "transcript": [
                TranscriptSegment(start_seconds=0.25, end_seconds=4.75, text="Caption fixture: first sentence."),
                TranscriptSegment(start_seconds=4.0, end_seconds=6.125, text="Caption fixture: second sentence."),
            ],
        }
        values.update(overrides)
        return StoredVideo(**values)
    return create


@pytest.fixture
def saved_videos(monkeypatch, chat_memory):
    """Repository seam only; repository/SDK tests exercise actual persistence code."""
    records = {}

    def get(video_id):
        row = records.get(video_id)
        return row.model_copy(deep=True) if row else None

    def upsert(record):
        validated = StoredVideo.model_validate(record.model_dump())
        records[record.video_id] = validated
        return validated.model_copy(deep=True)

    monkeypatch.setattr(video_repository, "get_video", Mock(side_effect=get))
    monkeypatch.setattr(video_repository, "upsert_video", Mock(side_effect=upsert))
    # Existing transcript/API tests mock the new RAG seams explicitly. Dedicated
    # RAG tests below exercise the actual indexing/retrieval implementations.
    from app.services import chat_service, video_service
    from app.schemas.chat import SourceSegment
    monkeypatch.setattr(video_service, "ensure_indexed", Mock())
    monkeypatch.setattr(chat_service, "run_agent", Mock(side_effect=lambda video, question, *args: (
        "Test answer grounded in the caption fixture.",
        [SourceSegment(**video.transcript[0].model_dump())],
    )))
    return records


@pytest.fixture
def chat_memory(monkeypatch):
    """A fake persistent repository shared by fresh apps within a test."""
    from types import SimpleNamespace
    from uuid import uuid4
    from threading import Lock
    from app.repositories import chat_repository as repo
    from app.schemas.error import ApiException
    store = SimpleNamespace(sessions={}, messages={}, summaries={}, lock=Lock())

    def claim(session_id, video_id, seconds=75):
        with store.lock:
            fresh = session_id is None
            if fresh:
                session_id = uuid4()
                store.sessions[session_id] = {"video_id": video_id, "revision": 0, "token": None}
                store.messages[session_id] = []
            row = store.sessions.get(session_id)
            if row is None or row["video_id"] != video_id:
                raise ApiException(404, "CONVERSATION_NOT_FOUND", "Conversation not found for this video.")
            if row["token"] is not None:
                raise ApiException(409, "CONVERSATION_BUSY", "Another message is being processed.")
            row["token"] = uuid4()
            return repo.Claim(session_id, row["token"], row["revision"], fresh)

    def history(claim, max_messages, max_chars):
        rows = store.messages[claim.session_id][-max_messages:]
        while rows and sum(len(row["content"]) for row in rows) > max_chars:
            rows = rows[1:]
        while rows and rows[0]["role"] != "user":
            rows = rows[1:]
        return [dict(row) for row in rows]

    def finish(claim, question, answer):
        with store.lock:
            row = store.sessions[claim.session_id]
            if row["token"] != claim.token or row["revision"] != claim.revision:
                raise ApiException(409, "CONVERSATION_BUSY", "The conversation changed.")
            messages = store.messages[claim.session_id]
            for role, content in [("user", question), ("assistant", answer)]:
                messages.append({"role": role, "content": content, "sequence_number": len(messages)})
            row["revision"] += 1
            row["token"] = None

    def release(claim):
        row = store.sessions.get(claim.session_id)
        if row and row["token"] == claim.token:
            if claim.fresh and row["revision"] == 0:
                del store.sessions[claim.session_id]
                del store.messages[claim.session_id]
            else:
                row["token"] = None

    monkeypatch.setattr(repo, "claim_session", claim)
    monkeypatch.setattr(repo, "get_history", history)
    monkeypatch.setattr(repo, "finish_exchange", finish)
    monkeypatch.setattr(repo, "release_session", release)
    monkeypatch.setattr(repo, "get_summary", lambda key, video_id: store.summaries.get((key, video_id)))
    monkeypatch.setattr(repo, "save_summary", lambda key, video_id, result: store.summaries.__setitem__((key, video_id), result))
    return store
