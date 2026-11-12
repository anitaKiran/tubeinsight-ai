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


def iter_video_ids(batch_size: int = 100):
    """Keyset pagination avoids loading all long transcripts during backfill."""
    previous = None
    while True:
        with get_supabase_client() as client:
            query = client.table("videos").select("video_id").order("video_id").limit(batch_size)
            if previous is not None:
                query = query.gt("video_id", previous)
            rows = query.execute().data
        if not rows:
            return
        for row in rows:
            yield row["video_id"]
        previous = rows[-1]["video_id"]
        if len(rows) < batch_size:
            return


def get_video_metadata(video_id: str):
    with get_supabase_client() as client:
        rows=client.table("videos").select("video_id,title,thumbnail_url").eq("video_id",video_id).limit(1).execute().data
    return rows[0] if rows else None


def iter_video_metadata(batch_size: int = 100, after_video_id: str | None = None):
    """Read small metadata pages, never full transcripts, for manual backfill."""
    previous=after_video_id
    while True:
        with get_supabase_client() as client:
            query=client.table("videos").select("video_id,title,thumbnail_url").order("video_id").limit(batch_size)
            if previous is not None:
                query=query.gt("video_id",previous)
            rows=query.execute().data
        if not rows:
            return
        yield from rows
        previous=rows[-1]["video_id"]
        if len(rows)<batch_size:
            return


def repair_missing_metadata(video: StoredVideo, title: str, thumbnail_url: str | None = None) -> StoredVideo:
    """Conditional PATCH per missing field; never upsert/delete or send captions.

    Equality with the read value prevents clobbering concurrent metadata repairs.
    A final read confirms persisted state, including a concurrent writer's title.
    """
    from app.services.youtube_metadata_service import missing, validate_id, valid_thumbnail
    validate_id(video.video_id)
    if not isinstance(title,str) or not title.strip() or len(title)>1000:
        raise ApiException(422,"VALIDATION_ERROR","Cannot save invalid video metadata.")
    fields={"title":title.strip()}
    thumbnail=valid_thumbnail(thumbnail_url,video.video_id)
    if thumbnail:
        fields["thumbnail_url"]=thumbnail
    with get_supabase_client() as client:
        for field,value in fields.items():
            original=getattr(video,field)
            if not missing(original):
                continue
            query=client.table("videos").update({field:value}).eq("video_id",video.video_id)
            query=query.is_(field,"null") if original is None else query.eq(field,original)
            query.execute()
    confirmed=get_video(video.video_id)
    if confirmed is None:
        raise ApiException(503,"DATABASE_UNAVAILABLE","Video metadata update could not be confirmed.")
    return confirmed
