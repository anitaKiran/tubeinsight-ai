"""Chat API models."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StrictStr, StringConstraints

from app.schemas.video import TranscriptSegment, VideoId


class ChatRequest(BaseModel):
    video_id: VideoId
    question: Annotated[
        StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    conversation_id: UUID | None = None


class SourceSegment(TranscriptSegment):
    """A cited transcript segment, using the video API timestamp structure."""


class ChatResponse(BaseModel):
    video_id: VideoId
    conversation_id: UUID
    mode: Literal["real"] = "real"
    answer: StrictStr
    sources: list[SourceSegment]
