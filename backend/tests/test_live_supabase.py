"""Opt-in live ingestion/readback with genuine captions, never fake database rows."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories import video_repository
from app.services import ingestion_service, mock_chat_service, youtube_transcript_service


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_SUPABASE_INTEGRATION") != "1", reason="Live Supabase check is opt-in.")
def test_live_ingestion_and_persistent_api_reads(monkeypatch):
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    video_id = os.getenv("YOUTUBE_TEST_VIDEO_ID", "Gfr50f6ZBvo")
    url = f"https://www.youtube.com/watch?v={video_id}"
    prepared = ingestion_service.ingest_video(url)
    assert prepared.video.transcript
    first = video_repository.get_video(video_id)
    second = video_repository.get_video(video_id)
    assert first == second == prepared.video

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("A saved video must not cause another YouTube request.")

    monkeypatch.setattr(youtube_transcript_service, "fetch_transcript_data", forbidden_fetch)
    assert ingestion_service.ingest_video(url).cached is True
    monkeypatch.setenv("TRANSCRIPT_SOURCE", "supabase")
    mock_chat_service.conversations.clear()
    try:
        for _ in range(2):
            with TestClient(create_app()) as client:
                response = client.post("/api/videos/process", json={"url": url})
                assert response.status_code == 200, response.text
                assert response.json()["mode"] == "real"
                assert response.json()["transcript"] == first.model_dump(mode="json")["transcript"]
        with TestClient(create_app()) as client:
            response = client.post("/api/chat/ask", json={"video_id": video_id, "question": "Hello"})
            assert response.status_code == 200
            assert response.json()["mode"] == "mock"
    finally:
        mock_chat_service.conversations.clear()
    print(f"Verified saved video {video_id}: {len(first.transcript)} segments; language={first.language}")
