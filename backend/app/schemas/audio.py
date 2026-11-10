from pydantic import BaseModel, StrictStr


class TranscriptionResponse(BaseModel):
    text: StrictStr
    language: StrictStr | None = None
    model: StrictStr
