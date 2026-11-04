"""Mock chat routes."""

from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.error import error_responses
from app.services import mock_chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post(
    "/ask", response_model=ChatResponse, responses=error_responses(404, 422, 500)
)
def ask_question(request: ChatRequest) -> ChatResponse:
    """Return a fixed simulated answer and remember the conversation's turns."""
    return mock_chat_service.ask_question(
        request.video_id, request.question, request.conversation_id
    )
