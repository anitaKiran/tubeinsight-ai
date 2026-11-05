"""Shared error envelope, service exception, and OpenAPI descriptions."""

from pydantic import BaseModel, StrictStr


class ApiError(BaseModel):
    code: StrictStr
    message: StrictStr


class ErrorResponse(BaseModel):
    error: ApiError


class ApiException(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_responses(*statuses: int, video_processing: bool = False) -> dict:
    """Document the shared envelope, including caption-provider failures."""
    errors = {
        400: [("INVALID_YOUTUBE_URL", "Please provide a valid YouTube URL.")],
        403: [("VIDEO_UNAVAILABLE", "This YouTube video is private or restricted.")],
        404: [
            ("VIDEO_NOT_FOUND", "Process this video before asking questions."),
            ("CONVERSATION_NOT_FOUND", "Conversation not found for this video."),
        ],
        422: [("VALIDATION_ERROR", "Missing or invalid request fields.")],
        429: [("YOUTUBE_RATE_LIMITED", "YouTube is rate limiting caption requests. Try again later.")],
        500: [
            ("INTERNAL_SERVER_ERROR", "An unexpected backend error occurred."),
            ("CONFIGURATION_ERROR", "Check backend Supabase settings and TRANSCRIPT_SOURCE (auto or supabase)."),
        ],
        502: [("INVALID_STORED_TRANSCRIPT", "The saved transcript is invalid. Prepare this video again locally.")],
        503: [("DATABASE_UNAVAILABLE", "Transcript storage is unavailable. Try again later.")],
        504: [("TRANSCRIPT_FETCH_TIMEOUT", "YouTube caption retrieval timed out. Try again later.")],
    }
    if video_processing:
        errors[404] = [
            ("TRANSCRIPT_NOT_CACHED", "This video has not been prepared yet."),
            ("TRANSCRIPT_NOT_AVAILABLE", "No transcript is available for this video."),
            ("VIDEO_UNAVAILABLE", "This YouTube video is unavailable."),
        ]
        errors[502].append(("TRANSCRIPT_FETCH_FAILED", "Could not retrieve YouTube captions. Try again later."))
        errors[503].append(("YOUTUBE_ACCESS_BLOCKED", "YouTube is blocking caption requests from this server."))
    responses = {}
    for status in statuses:
        examples = {
            code: {"value": {"error": {"code": code, "message": message}}}
            for code, message in errors[status]
        }
        responses[status] = {
            "model": ErrorResponse,
            "description": " / ".join(examples),
            "content": {"application/json": {"examples": examples}},
        }
    return responses
