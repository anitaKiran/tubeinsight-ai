"""Legacy import compatibility; all answers now use real RAG."""

from app.services.chat_service import ask_question, conversations

__all__ = ["ask_question", "conversations"]
