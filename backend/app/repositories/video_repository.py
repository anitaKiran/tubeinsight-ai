"""Read and atomically upsert validated transcripts through the Supabase SDK."""

from pydantic import ValidationError

from app.db.supabase_client import get_supabase_client
from app.schemas.error import ApiException
from app.schemas.stored_video import StoredVideo

_COLUMNS = "video_id,title,url,thumbnail_url,duration_seconds,language,transcript"


def _stored_row(row: dict, video_id: str) -> StoredVideo:
    try:
        video = StoredVideo.model_validate(row)
        if video.video_id != video_id:
            raise ValueError("Unexpected video identifier.")
        return video
    except (ValidationError, ValueError):
        raise ApiException(502, "INVALID_STORED_TRANSCRIPT", "The saved transcript is invalid. Prepare this video again locally.") from None


def get_video(video_id: str) -> StoredVideo | None:
    with get_supabase_client() as client:
        rows = client.table("videos").select(_COLUMNS).eq("video_id", video_id).limit(1).execute().data
        if not rows:
            return None
        return _stored_row(rows[0], video_id)


def upsert_video(video: StoredVideo | dict) -> StoredVideo:
    # Rebuild even existing models: do not allow unchecked mutation of a nested
    # segment to overwrite a valid cached transcript.
    try:
        record = StoredVideo.model_validate(
            video.model_dump() if isinstance(video, StoredVideo) else video
        )
    except ValidationError:
        raise ApiException(422, "VALIDATION_ERROR", "Cannot save an empty or invalid transcript.") from None
    with get_supabase_client() as client:
        rows = client.table("videos").upsert(
            record.model_dump(mode="json"), on_conflict="video_id"
        ).execute().data
        if not rows:
            raise ApiException(503, "DATABASE_UNAVAILABLE", "Transcript storage did not confirm the saved video.")
        return _stored_row(rows[0], record.video_id)
