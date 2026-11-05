"""Video processing routes."""

from fastapi import APIRouter

from app.schemas.error import error_responses
from app.schemas.video import VideoProcessRequest, VideoProcessResponse
from app.services import video_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post(
    "/process",
    response_model=VideoProcessResponse,
    responses=error_responses(400, 403, 404, 422, 429, 500, 502, 503, 504, video_processing=True),
)
def process_video(request: VideoProcessRequest) -> VideoProcessResponse:
    """Return saved captions; local auto mode fetches and saves missing captions."""
    return video_service.process_video(request.url)
