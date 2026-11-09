"""Video-grounded RAG chat routes."""

from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.error import error_responses
from app.services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post(
    "/ask", response_model=ChatResponse, responses=error_responses(404, 409, 422, 429, 500, 502, 503, 504)
)
def ask_question(request: ChatRequest) -> ChatResponse:
    """Retrieve evidence only from this video and return a grounded answer."""
    return chat_service.ask_question(
        request.video_id, request.question, request.conversation_id
    )
