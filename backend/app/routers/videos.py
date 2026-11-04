"""Video processing routes."""

from fastapi import APIRouter

from app.schemas.error import error_responses
from app.schemas.video import VideoProcessRequest, VideoProcessResponse
from app.services import mock_video_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post(
    "/process",
    response_model=VideoProcessResponse,
    responses=error_responses(400, 422, 500),
)
def process_video(request: VideoProcessRequest) -> VideoProcessResponse:
    """Return simulated metadata and transcript; never fetch YouTube content."""
    return mock_video_service.process_video(request.url)
