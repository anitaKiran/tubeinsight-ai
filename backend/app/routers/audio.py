from fastapi import APIRouter, UploadFile, File
from starlette.concurrency import run_in_threadpool

from app.schemas.audio import TranscriptionResponse
from app.schemas.error import ErrorResponse
from app.services import audio_service

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.post("/transcribe", response_model=TranscriptionResponse,
    responses={status: {"model": ErrorResponse} for status in (400, 413, 415, 422, 429, 500, 502, 503, 504)})
async def transcribe(file: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe a short recording in its original language; never store it."""
    data = None
    try:
        limit = audio_service.AudioSettings.from_env().max_bytes
        data = await file.read(limit + 1)
        return await run_in_threadpool(audio_service.transcribe_audio, data, file.filename or "")
    finally:
        data = None
        await file.close()
