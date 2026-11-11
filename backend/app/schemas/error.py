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
        409: [("VIDEO_NOT_INDEXED", "This saved transcript has not been indexed. Index it locally before asking questions.")],
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
    errors[422].append(("INDEXING_LIMIT_EXCEEDED", "Transcript exceeds configured local indexing limits."))
    errors[429].append(("RAG_RATE_LIMITED", "AI providers are rate limiting requests. Try again later."))
    errors[500].extend([
        ("PINECONE_INDEX_NOT_FOUND", "Create the configured Pinecone index before indexing."),
        ("PINECONE_INDEX_INCOMPATIBLE", "Pinecone embedding field, model, dimensions, and cosine metric must match backend configuration."),
    ])
    errors[502].append(("RAG_RESPONSE_INVALID", "The model did not return verifiable video sources. Please try again."))
    errors[503].extend([
        ("RAG_UNAVAILABLE", "AI providers are unavailable. Try again later."),
        ("INDEXING_PENDING", "Transcript is saved; Pinecone indexing confirmation is pending."),
    ])
    errors[504].extend([
        ("RAG_TIMEOUT", "AI provider request timed out. Try again later."),
        ("INDEXING_TIMEOUT", "Transcript is saved; local indexing reached its time limit."),
    ])
    errors[409].append(("CONVERSATION_BUSY", "Another message is being processed in this conversation. Retry shortly."))
    errors[422].extend([
        ("FOLLOWUP_CONTEXT_REQUIRED", "Please name the topic to explain; the available conversation does not identify that numbered point clearly."),
        ("INVALID_TIME_RANGE", "Use a valid interval within the configured retrieval window."),
        ("INVALID_TOOL_ARGUMENTS", "The transcript tool arguments are invalid."),
        ("SEGMENT_TOO_LARGE", "Request a smaller transcript interval."),
        ("SUMMARY_TOO_LONG", "Precompute this summary locally, then retry."),
        ("AGENT_LIMIT_REACHED", "Ask a smaller question within the configured execution limits."),
    ])
    errors[500].extend([
        ("MEMORY_NOT_CONFIGURED", "Apply backend/migrations/002_chat_memory_and_summaries.sql."),
        ("MODEL_TOOL_INCOMPATIBLE", "Configure a compatible native tool-calling model."),
    ])
    errors[502].extend([
        ("AGENT_TOOL_ERROR", "The transcript tool failed. Please try again."),
        ("INVALID_CHAT_HISTORY", "The saved conversation is invalid."),
        ("INVALID_SUMMARY_CACHE", "The saved summary references are invalid."),
    ])
    errors[504].append(("AGENT_TIMEOUT", "Chat reached its time limit. Ask a smaller question."))
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
