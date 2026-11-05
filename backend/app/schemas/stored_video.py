"""Internal persistence model; does not change the public video response."""

import math

from pydantic import BaseModel, Field, StrictStr, model_validator

from app.schemas.video import TranscriptSegment, VideoId


class StoredVideo(BaseModel):
    video_id: VideoId
    title: StrictStr | None = None
    url: StrictStr
    thumbnail_url: StrictStr | None = None
    duration_seconds: int | None = Field(default=None, strict=True, ge=0)
    language: StrictStr | None = None
    transcript: list[TranscriptSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transcript(self) -> "StoredVideo":
        for segment in self.transcript:
            if (
                not math.isfinite(segment.start_seconds)
                or not math.isfinite(segment.end_seconds)
                or segment.end_seconds < segment.start_seconds
            ):
                raise ValueError("Invalid caption timestamps.")
        if not any(segment.text.strip() for segment in self.transcript):
            raise ValueError("A transcript must contain caption text.")
        return self
