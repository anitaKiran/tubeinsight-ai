"""Optional local extraction check. HTTP processing no longer calls YouTube."""

import os

import pytest

from app.services.youtube_transcript_service import fetch_transcript_data


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_YOUTUBE_INTEGRATION") != "1", reason="Live YouTube check is opt-in.")
def test_public_youtube_transcript():
    video_id = os.getenv("YOUTUBE_TEST_VIDEO_ID", "Gfr50f6ZBvo")
    captions = fetch_transcript_data(video_id)
    assert captions.segments and captions.language
    assert all(0 <= segment.start_seconds <= segment.end_seconds for segment in captions.segments)
    print(f"Live captions: {len(captions.segments)} segments; language: {captions.language}")
