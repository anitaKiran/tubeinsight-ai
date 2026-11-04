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


def error_responses(*statuses: int) -> dict:
    """Use the same envelope in Swagger and in exception handlers."""
    errors = {
        400: (
            "INVALID_YOUTUBE_URL",
            "Please provide a valid YouTube URL.",
        ),
        404: ("VIDEO_NOT_FOUND", "Process this video before asking questions."),
        422: ("VALIDATION_ERROR", "Missing or invalid request fields."),
        500: ("INTERNAL_SERVER_ERROR", "An unexpected backend error occurred."),
    }
    responses = {}
    for status in statuses:
        code, message = errors[status]
        examples = {
            code: {"value": {"error": {"code": code, "message": message}}}
        }
        if status == 404:
            examples["CONVERSATION_NOT_FOUND"] = {
                "value": {
                    "error": {
                        "code": "CONVERSATION_NOT_FOUND",
                        "message": "Conversation not found for this video.",
                    }
                }
            }
        responses[status] = {
            "model": ErrorResponse,
            "description": " / ".join(examples),
            "content": {"application/json": {"examples": examples}},
        }
    return responses
