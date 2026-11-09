from unittest.mock import Mock
from types import SimpleNamespace
import json

import httpx2
from openai import OpenAI
import pytest

from app.agent import observability
from app.agent.model import AgentModel
from app.agent.settings import AgentSettings, Budget
from app.agent.tools import make_tools
from app.agent.evidence import Evidence
from app.rag.settings import RagSettings
from app.schemas.error import ApiException
from app.rag.answering import AnswerDraft


def test_tracing_absent_or_missing_key_is_optional(monkeypatch, caplog):
    factory = Mock()
    monkeypatch.setattr(observability, "Client", factory)
    with observability.observe_request("dQw4w9WgXcQ"):
        with observability.operation("tool.search_transcript", "tool"):
            pass
    factory.assert_not_called()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with observability.observe_request("dQw4w9WgXcQ"):
        pass
    factory.assert_not_called()
    assert "missing API key" in caplog.text


def test_enabled_traces_are_redacted_and_nested(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "unit-secret-langsmith")
    client = Mock()
    monkeypatch.setattr(observability, "Client", client)
    manager = Mock()
    manager.__enter__ = Mock(return_value=Mock())
    manager.__exit__ = Mock(return_value=False)
    trace = Mock(return_value=manager)
    monkeypatch.setattr(observability, "trace", trace)
    with observability.observe_request("dQw4w9WgXcQ"):
        with observability.operation("agent.model", "llm") as metadata:
            metadata["input_tokens"] = 10
    kwargs = client.call_args.kwargs
    assert kwargs["hide_inputs"] is True and kwargs["hide_outputs"] is True
    for call in trace.call_args_list:
        assert call.kwargs["inputs"] == {}
        assert set(call.kwargs["metadata"]) == {"operation", "video_id", "environment"}
        assert "unit-secret-langsmith" not in str(call.kwargs["metadata"])
    assert all(call.kwargs["outputs"] == {} for call in manager.__enter__.return_value.end.call_args_list)


def test_trace_export_failures_do_not_break_application(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "secret-langsmith-test")
    monkeypatch.setattr(observability, "Client", Mock())
    monkeypatch.setattr(observability, "trace", Mock(side_effect=RuntimeError("secret-langsmith-test")))
    reached = []
    with observability.observe_request("dQw4w9WgXcQ"):
        reached.append("normal application behavior")
    assert reached and "secret-langsmith-test" not in caplog.text
    with pytest.raises(ApiException) as caught:
        with observability.observe_request("dQw4w9WgXcQ"):
            raise ApiException(503, "RAG_UNAVAILABLE", "Original application error")
    assert caught.value.code == "RAG_UNAVAILABLE"


def test_sdk_diagnostics_do_not_expose_key_fragments(caplog):
    import logging
    logging.getLogger("langsmith.client").warning("SDK error: API Key: secret-key-fragment; response=private")
    assert "secret-key-fragment" not in caplog.text
    assert "private" not in caplog.text
    assert "Optional LangSmith SDK operation" in caplog.text


def test_installed_openai_integration_uses_real_native_tools(monkeypatch, make_record, chat_memory):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "unit-pinecone-key")
    settings, rag = AgentSettings(), RagSettings.from_env()
    budget = Budget(settings)
    captured = []
    def response(request):
        captured.append(json.loads(request.content))
        return httpx2.Response(200, json={"id": "chatcmpl-tool-unit", "object": "chat.completion", "created": 0,
            "model": "gpt-6-luna", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "call-actual-sdk", "type": "function",
                "function": {"name": "get_transcript_segment", "arguments": '{"start_seconds":150,"end_seconds":180}'}}]}}]})
    with OpenAI(api_key="unit-openai-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(response))) as client:
        model = AgentModel(rag, budget, client)
        video = make_record()
        tools = make_tools(video, Evidence(video.video_id), settings, rag, budget, model)
        result = model.invoke([{"role": "user", "content": "Explain 02:30 to 03:00"}], tools=tools)
    assert result.tool_calls[0]["name"] == "get_transcript_segment"
    assert result.tool_calls[0]["args"]["start_seconds"] == 150
    payload = captured[0]
    assert payload["tool_choice"] == "required" and payload["reasoning_effort"] == "none"
    assert {tool["function"]["name"] for tool in payload["tools"]} == {"search_transcript", "get_transcript_segment", "summarize_video"}
    for tool in payload["tools"]:
        assert "video_id" not in tool["function"]["parameters"].get("properties", {})


def test_structured_agent_calls_preserve_safe_token_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "unit-pinecone-key")
    def respond(request):
        return httpx2.Response(200, json={"id": "chatcmpl-json-unit", "object": "chat.completion", "created": 0,
            "model": "gpt-6-luna", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
            "content": json.dumps({"supported": True, "answer": "Grounded answer", "source_ids": [0]})}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}})
    with OpenAI(api_key="unit-openai-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(respond))) as client:
        budget = Budget(AgentSettings())
        result = AgentModel(RagSettings.from_env(), budget, client).invoke([{"role": "user", "content": "Question"}], schema=AnswerDraft)
    assert result.answer == "Grounded answer" and result.source_ids == [0]
    assert budget.model_calls == 1
