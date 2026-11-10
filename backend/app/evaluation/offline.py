"""Scripted providers exercise real services/tools. These are NOT AI quality scores."""
from contextlib import ExitStack, contextmanager
import json
import os
import re
import socket
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from app.agent.observability import operation
from app.rag.answering import AnswerDraft
from app.schemas.error import ApiException


class Memory:
    """Persistent test double shared across fresh application instances only."""
    def __init__(self):
        self.sessions, self.messages, self.summaries = {}, {}, {}

    def claim(self, session_id, video_id, seconds):
        from app.repositories.chat_repository import Claim
        fresh = session_id is None
        if fresh:
            session_id = uuid4()
            self.sessions[session_id] = {"video_id": video_id, "revision": 0, "token": None}
            self.messages[session_id] = []
        row = self.sessions.get(session_id)
        if row is None or row["video_id"] != video_id:
            raise ApiException(404, "CONVERSATION_NOT_FOUND", "Conversation not found for this video.")
        if row["token"] is not None:
            raise ApiException(409, "CONVERSATION_BUSY", "Another request is running.")
        row["token"] = uuid4()
        return Claim(session_id, row["token"], row["revision"], fresh)

    def history(self, claim, max_messages, max_chars):
        rows = self.messages[claim.session_id][-max_messages:]
        while rows and (sum(len(r["content"]) for r in rows) > max_chars or rows[0]["role"] != "user"):
            rows = rows[1:]
        return [dict(r) for r in rows]

    def finish(self, claim, question, answer):
        row = self.sessions[claim.session_id]
        if row["token"] != claim.token or row["revision"] != claim.revision:
            raise ApiException(409, "CONVERSATION_BUSY", "Conversation changed.")
        rows = self.messages[claim.session_id]
        for role, content in (("user", question), ("assistant", answer)):
            rows.append({"role": role, "content": content, "sequence_number": len(rows)})
        row.update(token=None, revision=row["revision"]+1)

    def release(self, claim):
        row = self.sessions[claim.session_id]
        if row["token"] == claim.token:
            row["token"] = None
            if claim.fresh and not self.messages[claim.session_id]:
                del self.sessions[claim.session_id]
                del self.messages[claim.session_id]


class ScriptedModel:
    def __init__(self, budget):
        self.budget = budget

    def invoke(self, messages, *, tools=None, schema=None, name="agent.model"):
        self.budget.model()
        with operation(name, "llm"):
            if tools:
                question = messages[-1].content.casefold()
                calls = []
                times = re.findall(r"\d{1,2}:\d{2}", question)
                if "summar" in question or "topic" in question or "takeaway" in question:
                    tool, args = "summarize_video", {}
                    if len(times) == 2:
                        args = {"start_seconds": times[0], "end_seconds": times[1]}
                elif times:
                    tool, args = "get_transcript_segment", {"start_seconds": times[0]}
                    if len(times) > 1:
                        args["end_seconds"] = times[1]
                else:
                    tool, args = "search_transcript", {"query": question}
                    if "second one" in question:
                        previous = [m.content for m in messages if isinstance(m, AIMessage)]
                        if previous and len(previous[-1].splitlines()) > 1:
                            args["query"] = previous[-1].splitlines()[1]
                calls.append({"id": "offline-call-1", "name": tool, "args": args})
                if "also search" in question:
                    calls.append({"id": "offline-call-2", "name": "search_transcript", "args": {"query": "basil"}})
                return AIMessage(content="", tool_calls=calls)
            if name.startswith("summary."):
                payload = json.loads(messages[-1].content)
                rows = payload.get("material", payload.get("evidence", []))
            else:
                rows = [row for m in messages if isinstance(m, ToolMessage) for row in json.loads(m.content).get("results", [])]
            return AnswerDraft(supported=bool(rows), answer="\n".join(r["text"] for r in rows),
                source_ids=list(dict.fromkeys(r["evidence_id"] for r in rows)))


def retrieve(video, query):
    tokens = set(re.findall(r"\w+", query.casefold())) - {"what", "is", "the", "a", "an", "of", "in", "and", "how", "does", "it", "tell", "me", "about", "speaker", "s", "please"}
    result = []
    for index, segment in enumerate(video.transcript):
        if tokens & set(re.findall(r"\w+", segment.text.casefold())):
            result.append(Document(page_content=segment.text, metadata={"start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds, "chunk_index": index, "similarity_score": 1.0}))
    return result


@contextmanager
def offline_services(dataset):
    from app.agent import runner, tools
    from app.repositories import chat_repository as chat, video_repository as videos
    from app.services import audio_service
    import httpx
    import httpx2
    import requests
    import urllib3
    memory = Memory()
    records = {v.video_id: v for v in dataset.videos}
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline evaluation attempted an external network request.")
    @contextmanager
    def model(settings, budget):
        yield ScriptedModel(budget)
    def fake_client(**kwargs):
        client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **k:
            SimpleNamespace(text="What are the main topics in this video?", languages=[{"code": "en"}]))))
        from unittest.mock import MagicMock
        manager = MagicMock()
        manager.__enter__.return_value = client
        return manager
    original_connect = socket.socket.connect
    def local_event_loop_socket(sock, address):
        # Windows asyncio creates a TCP socketpair on loopback for its wakeup
        # pipe. Permit that local mechanism; all remote transports stay blocked.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        return forbidden()
    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, "connect", local_event_loop_socket))
        stack.enter_context(patch.dict(os.environ, {"LANGSMITH_TRACING": "false", "LANGSMITH_API_KEY": "", "OPENAI_API_KEY": "offline-fixture",
            "PINECONE_API_KEY": "offline-fixture", "PINECONE_INDEX_NAME": "tubechunks", "OPENAI_CHAT_MODEL": "gpt-6-luna",
            "PINECONE_EMBEDDING_FIELD": "chunk_text", "PINECONE_EMBEDDING_MODEL": "llama-text-embed-v2", "PINECONE_EMBEDDING_DIMENSIONS": "1024",
            "TRANSCRIPT_SOURCE": "supabase", "APP_ENV": "test", "AGENT_MAX_MODEL_CALLS": "6", "AGENT_MAX_TOOL_CALLS": "3"}))
        for target, attr in [(socket, "create_connection"), (httpx.HTTPTransport, "handle_request"),
            (httpx2.HTTPTransport, "handle_request"), (requests.Session, "send"), (urllib3.PoolManager, "request")]:
            stack.enter_context(patch.object(target, attr, forbidden))
        for target, attr, value in [(videos,"get_video",lambda vid: records.get(vid)), (chat,"claim_session",memory.claim),
            (chat,"get_history",memory.history), (chat,"finish_exchange",memory.finish), (chat,"release_session",memory.release),
            (chat,"get_summary",lambda key, vid: memory.summaries.get((key, vid))),
            (chat,"save_summary",lambda key, vid, result: memory.summaries.__setitem__((key, vid), result)),
            (runner,"open_agent_model",model), (tools,"retrieve_evidence",retrieve), (audio_service,"OpenAI",fake_client)]:
            stack.enter_context(patch.object(target, attr, value))
        yield memory
