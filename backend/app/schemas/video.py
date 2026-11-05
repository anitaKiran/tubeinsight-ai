"""Video API models. All timestamps are seconds from the start of the video."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictStr, StringConstraints

VideoId = Annotated[
    StrictStr, StringConstraints(pattern=r"^[A-Za-z0-9_-]{11}$")
]


class VideoProcessRequest(BaseModel):
    url: StrictStr = Field(
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    )


class VideoMetadata(BaseModel):
    id: VideoId
    title: StrictStr | None
    url: StrictStr
    thumbnail_url: StrictStr
    duration_seconds: Annotated[int, Field(strict=True, ge=0)] | None


class TranscriptSegment(BaseModel):
    start_seconds: Annotated[float, Field(strict=True, ge=0)]
    end_seconds: Annotated[float, Field(strict=True, ge=0)]
    text: StrictStr


class VideoProcessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    mode: Literal["real"] = "real"
    video: VideoMetadata
    transcript: list[TranscriptSegment]
