"""In-memory conversations with fixed simulated answers, without an LLM."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.schemas.chat import ChatResponse, SourceSegment
from app.schemas.error import ApiException
from app.runtime import get_transcript_source
from app.repositories import video_repository

MOCK_ANSWER = (
    "This is a simulated AI response for frontend development. "
    "Real answers will be generated from the video transcript in a future version."
)


@dataclass
class ChatTurn:
    question: str
    answer: str


@dataclass
class Conversation:
    video_id: str
    history: list[ChatTurn] = field(default_factory=list)


conversations: dict[UUID, Conversation] = {}


def ask_question(
    video_id: str, question: str, conversation_id: UUID | None
) -> ChatResponse:
    get_transcript_source()  # Validate settings; chat always reads saved captions.
    video = video_repository.get_video(video_id)
    if video is None:
        raise ApiException(
            404, "VIDEO_NOT_FOUND", "This video has not been prepared yet."
        )

    if conversation_id is None:
        conversation_id = uuid4()
        conversation = Conversation(video_id=video_id)
        conversations[conversation_id] = conversation
    else:
        conversation = conversations.get(conversation_id)
        if conversation is None or conversation.video_id != video_id:
            raise ApiException(
                404, "CONVERSATION_NOT_FOUND", "Conversation not found for this video."
            )

    conversation.history.append(ChatTurn(question=question, answer=MOCK_ANSWER))
    return ChatResponse(
        video_id=video_id,
        conversation_id=conversation_id,
        answer=MOCK_ANSWER,
        sources=[SourceSegment(**video.transcript[0].model_dump())],
    )
