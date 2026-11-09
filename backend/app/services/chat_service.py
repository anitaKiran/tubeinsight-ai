"""Persistent video-bound conversations; atomic exchanges survive server restarts."""
import logging
from uuid import UUID

from app.agent.settings import AgentSettings, Budget
from app.agent.runner import run_agent
from app.agent.privacy import redact
from app.agent.observability import observe_request, operation
from app.repositories import video_repository, chat_repository
from app.runtime import get_transcript_source
from app.schemas.chat import ChatResponse
from app.schemas.error import ApiException

logger = logging.getLogger(__name__)


def ask_question(video_id: str, question: str, conversation_id: UUID | None) -> ChatResponse:
    get_transcript_source()
    settings = AgentSettings.from_env()
    budget = Budget(settings)
    question = redact(question)
    with observe_request(video_id):
        video = video_repository.get_video(video_id)
        if video is None:
            raise ApiException(404, "VIDEO_NOT_FOUND", "This video has not been prepared yet.")
        with operation("memory.claim"):
            claim = chat_repository.claim_session(conversation_id, video_id, min(300, settings.request_seconds + 20))
        completed = False
        try:
            with operation("memory.history"):
                history = chat_repository.get_history(claim, settings.history_messages, settings.history_chars)
            answer, sources = run_agent(video, question, history, settings, budget)
            answer = redact(answer)
            budget.remaining()
            with operation("memory.persist"):
                chat_repository.finish_exchange(claim, question, answer)
            completed = True
            return ChatResponse(video_id=video_id, conversation_id=claim.session_id, mode="real", answer=answer, sources=sources)
        finally:
            if not completed:
                try:
                    chat_repository.release_session(claim)
                except Exception:
                    # The database lease expires even when best-effort release
                    # cannot reach Supabase. Never mask the original safe error.
                    logger.warning("Conversation lease release failed; lease will expire.")
