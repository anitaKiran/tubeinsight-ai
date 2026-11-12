"""Local ingestion and batch CLI behavior with mocked YouTube and storage."""

from unittest.mock import Mock

import pytest
from requests import Timeout
from youtube_transcript_api import RequestBlocked, TranscriptsDisabled

from app.repositories import video_repository
from app.schemas.error import ApiException
from app.scripts import ingest_video, ingest_videos
from app.services import ingestion_service, youtube_transcript_service

VIDEO_ID = "dQw4w9WgXcQ"
URL = f"https://youtu.be/{VIDEO_ID}"


def test_successful_local_ingestion(saved_videos, caption_api):
    result = ingestion_service.ingest_video(URL)
    assert result.cached is False
    assert result.video.language == "en"
    assert result.video.transcript[0].start_seconds == 0.25
    assert result.video.transcript[0].end_seconds == 4.75
    assert result.video.transcript[1].start_seconds == 4.0
    assert saved_videos[VIDEO_ID] == result.video


def test_duplicate_skips_youtube(saved_videos, make_record, caption_api):
    saved_videos[VIDEO_ID] = make_record()
    result = ingestion_service.ingest_video(URL)
    assert result.cached is True
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


def test_force_refresh_uses_actual_caption_language(saved_videos, make_record, caption_api, make_track):
    saved_videos[VIDEO_ID] = make_record(title="Old title")
    caption_api.list.return_value = [make_track(language="de", generated=True)]
    result = ingestion_service.ingest_video(URL, force=True)
    assert result.cached is False
    assert result.video.language == "de"
    assert saved_videos[VIDEO_ID].language == "de"
    assert result.video.title == "Old title"  # Transcript refresh preserves metadata.


@pytest.mark.parametrize("error", [TranscriptsDisabled(VIDEO_ID), Timeout("secret"), RequestBlocked(VIDEO_ID)])
def test_failed_force_refresh_preserves_existing_video(saved_videos, make_record, caption_api, error):
    original = make_record()
    saved_videos[VIDEO_ID] = original
    caption_api.list.side_effect = error
    with pytest.raises(ApiException):
        ingestion_service.ingest_video(URL, force=True)
    assert saved_videos[VIDEO_ID] == original
    video_repository.upsert_video.assert_not_called()


def test_empty_extraction_never_saves(saved_videos, caption_api, make_track):
    caption_api.list.return_value = [make_track(snippets=[])]
    with pytest.raises(ApiException) as caught:
        ingestion_service.ingest_video(URL)
    assert caught.value.code == "TRANSCRIPT_NOT_AVAILABLE"
    assert not saved_videos


def test_empty_provider_result_rejected_even_if_provider_is_replaced(saved_videos, monkeypatch):
    monkeypatch.setattr(youtube_transcript_service, "fetch_transcript_data", lambda _: youtube_transcript_service.CaptionTranscript([], "en"))
    with pytest.raises(ApiException) as caught:
        ingestion_service.ingest_video(URL)
    assert caught.value.code == "VALIDATION_ERROR"
    video_repository.upsert_video.assert_not_called()


def test_force_can_repair_corrupt_saved_row(saved_videos, caption_api):
    video_repository.get_video.side_effect = ApiException(502, "INVALID_STORED_TRANSCRIPT", "Invalid row.")
    result = ingestion_service.ingest_video(URL, force=True)
    assert result.cached is False
    assert saved_videos[VIDEO_ID].transcript


def test_database_read_failure_does_not_trigger_extraction(saved_videos, caption_api):
    video_repository.get_video.side_effect = ApiException(503, "DATABASE_UNAVAILABLE", "Unavailable.")
    with pytest.raises(ApiException):
        ingestion_service.ingest_video(URL, force=True)
    caption_api.list.assert_not_called()
    video_repository.upsert_video.assert_not_called()


def test_invalid_url_never_reaches_database(saved_videos, caption_api):
    with pytest.raises(ApiException) as caught:
        ingestion_service.ingest_video("https://evil.example/watch?v=" + VIDEO_ID)
    assert caught.value.code == "INVALID_YOUTUBE_URL"
    video_repository.get_video.assert_not_called()
    caption_api.list.assert_not_called()


def test_ingestion_refuses_to_run_on_vercel(saved_videos, caption_api, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ApiException) as caught:
        ingestion_service.ingest_video(URL)
    assert caught.value.code == "CONFIGURATION_ERROR"
    caption_api.list.assert_not_called()
    video_repository.get_video.assert_not_called()


def test_single_cli_success_and_cache(saved_videos, caption_api, capsys):
    assert ingest_video.main([URL]) == 0
    output = capsys.readouterr().out
    assert "tubeInsight-ai Transcript Ingestion" in output
    assert "Transcript segments: 2" in output
    assert "Language: en" in output
    assert "Saved to Supabase successfully" in output
    assert ingest_video.main([URL]) == 0
    assert "Cached in Supabase" in capsys.readouterr().out
    assert caption_api.list.call_count == 1


def test_cli_failure_exit_code_and_no_traceback(saved_videos, caption_api, capsys):
    caption_api.list.side_effect = Timeout("sensitive-test-details")
    assert ingest_video.main([URL]) == 1
    output = capsys.readouterr().err
    assert "TRANSCRIPT_FETCH_TIMEOUT" in output
    assert "sensitive-test-details" not in output
    assert "Traceback" not in output


def test_batch_processes_each_line_independently(saved_videos, caption_api, tmp_path, capsys):
    file = tmp_path / "videos.txt"
    file.write_text("\ufeff# Demo list\n\n" + URL + "\nnot-a-url\n" + URL + "\n", encoding="utf-8")
    assert ingest_videos.main([str(file)]) == 1
    output = capsys.readouterr()
    assert "Saved: 1; Cached: 1; Failed: 1; Successes: 2" in output.out
    assert "INVALID_YOUTUBE_URL" in output.err
    assert caption_api.list.call_count == 1


def test_batch_force_refresh(saved_videos, make_record, caption_api, tmp_path):
    saved_videos[VIDEO_ID] = make_record()
    file = tmp_path / "videos.txt"
    file.write_text(URL, encoding="utf-8")
    assert ingest_videos.main([str(file), "--force"]) == 0
    caption_api.list.assert_called_once()


def test_missing_batch_file_is_safe(tmp_path, capsys):
    assert ingest_videos.main([str(tmp_path / "missing.txt")]) == 1
    assert "Could not read" in capsys.readouterr().err
