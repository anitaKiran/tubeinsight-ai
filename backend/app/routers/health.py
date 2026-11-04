"""Health check for frontend connectivity."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.error import error_responses

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["videowise-api"] = "videowise-api"
    mode: Literal["mock"] = "mock"


@router.get("/health", response_model=HealthResponse, responses=error_responses(500))
def health() -> HealthResponse:
    return HealthResponse()
