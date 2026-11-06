"""Run from backend/: python -m uvicorn app.main:app --reload."""

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.routers import chat, health, videos
from app.schemas.error import ApiError, ApiException, ErrorResponse

logger = logging.getLogger(__name__)
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:3000"


def get_cors_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ]
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or "*" in origin
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS_ORIGINS must contain exact HTTP(S) origins.")
        # Validate malformed ports as well as malformed hosts.
        _ = parsed.port
    return origins


def error_response(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ApiError(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app() -> CORSMiddleware:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api = FastAPI(
        title="tubeInsight-ai API",
        version="0.4.0",
        description=(
            "Supabase-first captions with automatic local extraction in auto mode. "
            "Production and Vercel use saved captions only. Chat uses video-isolated RAG."
        ),
    )

    @api.exception_handler(ApiException)
    async def handle_api_error(request: Request, exc: ApiException) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @api.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Summarize field locations without echoing raw user input or exceptions.
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        return error_response(
            422, "VALIDATION_ERROR", f"Missing or invalid request fields: {', '.join(fields)}."
        )

    @api.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        response = error_response(
            exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @api.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected backend error on %s", request.url.path)
        return error_response(
            500, "INTERNAL_SERVER_ERROR", "An unexpected backend error occurred."
        )

    api.include_router(health.router)
    api.include_router(videos.router)
    api.include_router(chat.router)

    # Wrap the entire app so even unexpected 500 responses receive CORS headers.
    return CORSMiddleware(
        api,
        allow_origins=get_cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )


app = create_app()
