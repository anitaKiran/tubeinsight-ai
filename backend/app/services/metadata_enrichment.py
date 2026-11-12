"""Repair missing metadata without replacing a transcript or claiming unsaved success."""
import logging
from app.repositories import video_repository
from app.services import youtube_metadata_service as provider

logger=logging.getLogger(__name__)


def enrich_cached_video(video):
    if not provider.missing(video.title):
        return video
    metadata=provider.fetch_metadata(video.video_id)
    if metadata is None:
        return video
    try:
        return video_repository.repair_missing_metadata(video,metadata.title,metadata.thumbnail_url)
    except Exception:
        logger.warning("Video metadata persistence unconfirmed: video=%s reason=storage_update_failed",video.video_id)
        return video  # Preserve valid captions; do not return an unsaved title.
