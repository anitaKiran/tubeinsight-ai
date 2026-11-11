"""Three actual LangChain tools, closed over trusted video and request context."""
from typing import Annotated, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictStr

from app.agent.observability import operation
from app.agent.context import resolve_search_query
from app.agent.timestamps import seconds, select_range
from app.rag.answering import retrieve_evidence
from app.schemas.error import ApiException

Timestamp = Annotated[float, BeforeValidator(seconds)]


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(min_length=1, max_length=2000)


class RangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_seconds: Timestamp
    end_seconds: Timestamp | None = None


class SummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: Literal["brief", "detailed"] = "brief"
    start_seconds: Timestamp | None = None
    end_seconds: Timestamp | None = None


def make_tools(video, ledger, settings, rag_settings, budget, model, *, history=()):
    def search_transcript(query):
        """Search the selected video's transcript for a topic or resolved follow-up question. Returns original evidence and timestamps."""
        with operation("tool.search_transcript", "tool"):
            budget.remaining()
            query = resolve_search_query(query, history)
            with operation("pinecone.retrieval", "retriever"):
                documents = retrieve_evidence(video, query)
            rows = [ledger.add(doc.page_content, doc.metadata["start_seconds"], doc.metadata["end_seconds"],
                chunk_id=str(doc.metadata["chunk_index"]), similarity_score=doc.metadata.get("similarity_score")) for doc in documents]
            return {"results": rows, "empty": not rows}

    def get_transcript_segment(start_seconds, end_seconds=None):
        """Retrieve original captions for a time interval, or around one timestamp when end_seconds is omitted. Accepts seconds, MM:SS and HH:MM:SS. Never uses Pinecone."""
        with operation("tool.get_transcript_segment", "tool"):
            budget.remaining()
            segments = select_range(video, start_seconds, end_seconds, settings)
            if sum(len(s.text) for s in segments) > settings.tool_chars:
                raise ApiException(422, "SEGMENT_TOO_LARGE", "This transcript interval is too large. Request a smaller interval.")
            return {"results": [ledger.add(s.text, s.start_seconds, s.end_seconds) for s in segments], "empty": not segments}

    def summarize_video(detail="brief", start_seconds=None, end_seconds=None):
        """Summarize the WHOLE selected video or a specified interval, briefly or in detail. Use this for main ideas, takeaways, and all full-video summaries; do not substitute a few search hits."""
        from app.agent.summarization import summarize
        with operation("tool.summarize_video", "tool"):
            return summarize(video, ledger, settings, rag_settings, budget, model,
                detail=detail, start=start_seconds, end=end_seconds)

    return [StructuredTool.from_function(function, args_schema=schema) for function, schema in [
        (search_transcript, SearchArgs), (get_transcript_segment, RangeArgs), (summarize_video, SummaryArgs),
    ]]
