"""Real single-question RAG with the existing in-process conversation contract."""

from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.rag.answering import answer_question
from app.repositories import video_repository
from app.runtime import get_transcript_source
from app.schemas.chat import ChatResponse
from app.schemas.error import ApiException


@dataclass
class ChatTurn:
    question: str
    answer: str


@dataclass
class Conversation:
    video_id: str
    history: list[ChatTurn] = field(default_factory=list)


# Compatibility state only: history is NOT sent to the model as conversational
# memory. It is bounded and may disappear on restarts or another Vercel instance.
conversations: OrderedDict[UUID, Conversation] = OrderedDict()


def ask_question(video_id: str, question: str, conversation_id: UUID | None) -> ChatResponse:
    get_transcript_source()
    video = video_repository.get_video(video_id)
    if video is None:
        raise ApiException(404, "VIDEO_NOT_FOUND", "This video has not been prepared yet.")
    conversation = conversations.get(conversation_id) if conversation_id else None
    if conversation_id is not None and (conversation is None or conversation.video_id != video_id):
        raise ApiException(404, "CONVERSATION_NOT_FOUND", "Conversation not found for this video.")
    answer, sources = answer_question(video, question)
    if conversation_id is None:
        conversation_id = uuid4()
        conversation = Conversation(video_id)
        if len(conversations) >= 256:
            conversations.popitem(last=False)
        conversations[conversation_id] = conversation
    conversation.history.append(ChatTurn(question, answer))
    del conversation.history[:-20]
    conversations.move_to_end(conversation_id)
    return ChatResponse(video_id=video_id, conversation_id=conversation_id, mode="real", answer=answer, sources=sources)
