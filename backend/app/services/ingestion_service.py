"""Shared local ingestion for automatic HTTP caching and the optional CLI."""

from dataclasses import dataclass

from pydantic import ValidationError

from app.repositories import video_repository
from app.schemas.error import ApiException
from app.schemas.stored_video import StoredVideo
from app.services import youtube_transcript_service
from app.services.youtube_url import extract_video_id
from app.runtime import require_local_extraction


@dataclass(frozen=True)
class IngestionResult:
    video: StoredVideo
    cached: bool


def ingest_video(url: str, *, force: bool = False) -> IngestionResult:
    video_id = extract_video_id(url)
    require_local_extraction()
    try:
        existing = video_repository.get_video(video_id)
    except ApiException as exc:
        if not (force and exc.code == "INVALID_STORED_TRANSCRIPT"):
            raise
        existing = None
    if existing is not None and not force:
        return IngestionResult(video=existing, cached=True)
    # Failed extraction/validation never reaches the atomic upsert. The previous
    # row stays intact on --force failures; there is no delete-then-insert step.
    captions = youtube_transcript_service.fetch_transcript_data(video_id)
    try:
        record = StoredVideo(
            video_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            language=captions.language, transcript=captions.segments,
        )
    except ValidationError:
        raise ApiException(422, "VALIDATION_ERROR", "Cannot save an empty or invalid transcript.") from None
    return IngestionResult(video=video_repository.upsert_video(record), cached=False)
