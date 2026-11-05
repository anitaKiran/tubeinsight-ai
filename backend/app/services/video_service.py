"""Supabase-first processing with automatic local extraction on cache misses."""

from app.schemas.error import ApiException
from app.schemas.video import VideoMetadata, VideoProcessResponse
from app.runtime import get_transcript_source
from app.services import ingestion_service
from app.services.youtube_url import extract_video_id
from app.repositories import video_repository
from app.schemas.stored_video import StoredVideo


def video_response(record: StoredVideo) -> VideoProcessResponse:
    video_id = record.video_id
    return VideoProcessResponse(
        mode="real",
        video=VideoMetadata(
            id=video_id,
            title=record.title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=record.thumbnail_url or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            duration_seconds=record.duration_seconds,
        ),
        transcript=record.transcript,
    )


def process_video(url: str) -> VideoProcessResponse:
    video_id = extract_video_id(url)
    source = get_transcript_source()
    if source == "auto":
        return video_response(ingestion_service.ingest_video(url).video)
    record = video_repository.get_video(video_id)
    if record is None:
        raise ApiException(404, "TRANSCRIPT_NOT_CACHED", "This video has not been prepared yet.")
    return video_response(record)
