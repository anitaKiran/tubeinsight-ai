"""Optional live check; never required for the ordinary automated test suite."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import mock_chat_service, video_service


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_YOUTUBE_INTEGRATION") != "1", reason="Live YouTube check is opt-in."
)
def test_public_youtube_transcript():
    video_id = os.getenv("YOUTUBE_TEST_VIDEO_ID", "Gfr50f6ZBvo")
    try:
        with TestClient(create_app()) as client:
            response = client.post("/api/videos/process", json={
                "url": f"https://www.youtube.com/watch?v={video_id}"
            })
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["mode"] == "real"
            assert body["video"]["id"] == video_id
            assert body["transcript"]
            assert any(segment["text"].strip() for segment in body["transcript"])
            assert all(
                0 <= segment["start_seconds"] <= segment["end_seconds"]
                for segment in body["transcript"]
            )
            chat = client.post("/api/chat/ask", json={
                "video_id": video_id, "question": "What is this video about?"
            })
            assert chat.status_code == 200
            assert chat.json()["mode"] == "mock"
            print(f"Live captions: {len(body['transcript'])} segments")
            print(body["transcript"][:3])
    finally:
        video_service.processed_videos.clear()
        mock_chat_service.conversations.clear()
