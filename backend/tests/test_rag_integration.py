"""HTTP and CLI integration over mocked RAG boundaries and saved captions."""

from dataclasses import dataclass
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.rag import answering
from app.rag.indexing import IndexingResult
from app.repositories import video_repository
from app.schemas.error import ApiException
from app.scripts import index_cached_videos as cli
from app.services import chat_service, video_service, youtube_transcript_service

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("status,code", [(409, "VIDEO_NOT_INDEXED"), (503, "RAG_UNAVAILABLE"), (429, "RAG_RATE_LIMITED"), (504, "RAG_TIMEOUT"), (500, "CONFIGURATION_ERROR")])
def test_chat_failure_is_clear_and_never_fake(saved_videos, make_record, monkeypatch, status, code, chat_memory):
    saved_videos[VIDEO_ID] = make_record()
    monkeypatch.setattr(chat_service, "run_agent", Mock(side_effect=ApiException(status, code, "Safe setup or provider error.")))
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/api/chat/ask", json={"video_id": VIDEO_ID, "question": "What does this say?"})
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": "Safe setup or provider error."}}
    assert not chat_memory.sessions


def test_local_video_processing_indexes_saved_transcript(saved_videos, make_record):
    saved_videos[VIDEO_ID] = make_record()
    response = video_service.process_video("https://youtu.be/" + VIDEO_ID)
    assert response.mode == "real"
    video_service.ensure_indexed.assert_called_once_with(saved_videos[VIDEO_ID])


def test_failed_indexing_preserves_original_transcript(saved_videos, make_record):
    original = make_record()
    saved_videos[VIDEO_ID] = original
    video_service.ensure_indexed.side_effect = ApiException(503, "RAG_UNAVAILABLE", "Index unavailable.")
    with pytest.raises(ApiException):
        video_service.process_video("https://youtu.be/" + VIDEO_ID)
    assert saved_videos[VIDEO_ID] == original
    video_repository.upsert_video.assert_not_called()


@pytest.mark.parametrize("deployment", [{"VERCEL": "1"}, {"VERCEL_ENV": "preview"}, {"APP_ENV": "production"}])
def test_serverless_processing_never_indexes(saved_videos, make_record, monkeypatch, deployment):
    saved_videos[VIDEO_ID] = make_record()
    for key, value in deployment.items():
        monkeypatch.setenv(key, value)
    assert video_service.process_video("https://youtu.be/" + VIDEO_ID).mode == "real"
    video_service.ensure_indexed.assert_not_called()


def test_one_video_cli_backfill_is_idempotent_and_never_fetches_youtube(saved_videos, make_record, caption_api, monkeypatch, capsys):
    saved_videos[VIDEO_ID] = make_record()
    ensure = Mock(side_effect=[IndexingResult(VIDEO_ID, 2, False), IndexingResult(VIDEO_ID, 2, True)])
    monkeypatch.setattr(cli, "ensure_indexed", ensure)
    assert cli.main(["--video-id", VIDEO_ID]) == 0
    assert "indexed; chunks=2" in capsys.readouterr().out
    assert cli.main(["--video-id", VIDEO_ID]) == 0
    assert "already indexed" in capsys.readouterr().out
    caption_api.list.assert_not_called()


def test_explicit_backfill_limit_and_independent_failures(saved_videos, make_record, monkeypatch, capsys):
    other = "abcdefghijk"
    saved_videos[VIDEO_ID] = make_record()
    saved_videos[other] = make_record(other)
    monkeypatch.setattr(video_repository, "iter_video_ids", lambda: iter([VIDEO_ID, other, "01234567890"]))
    ensure = Mock(side_effect=[ApiException(503, "RAG_UNAVAILABLE", "Try later."), IndexingResult(other, 2, False)])
    monkeypatch.setattr(cli, "ensure_indexed", ensure)
    assert cli.main(["--all", "--limit", "2"]) == 1
    assert ensure.call_count == 2
    assert "Processed: 2; Failed: 1" in capsys.readouterr().out


def test_backfill_missing_video_and_production_guard(saved_videos, monkeypatch, capsys):
    ensure = Mock()
    monkeypatch.setattr(cli, "ensure_indexed", ensure)
    assert cli.main(["--video-id", VIDEO_ID]) == 1
    assert "VIDEO_NOT_FOUND" in capsys.readouterr().err
    monkeypatch.setenv("APP_ENV", "production")
    assert cli.main(["--video-id", VIDEO_ID]) == 1
    assert "CONFIGURATION_ERROR" in capsys.readouterr().err
    ensure.assert_not_called()
