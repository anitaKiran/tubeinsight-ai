"""Legacy ask_question import; all chat now uses durable agent sessions."""
from app.services.chat_service import ask_question

__all__ = ["ask_question"]
