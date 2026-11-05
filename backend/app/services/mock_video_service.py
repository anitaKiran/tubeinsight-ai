"""Legacy import compatibility; video processing now retrieves real captions."""

from app.services.video_service import extract_video_id, process_video, processed_videos

__all__ = ["extract_video_id", "process_video", "processed_videos"]
