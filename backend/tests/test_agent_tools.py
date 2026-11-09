"""Actual LangChain tool execution and full-coverage summary orchestration."""
from dataclasses import replace
import json

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from pydantic import ValidationError
import pytest

from app.agent.evidence import Evidence
from app.agent.settings import AgentSettings, Budget
from app.agent.timestamps import seconds
from app.agent.tools import make_tools
from app.agent import tools as tool_module, summarization
from app.rag.settings import RagSettings
from app.rag.answering import AnswerDraft
from app.schemas.error import ApiException
from app.schemas.video import TranscriptSegment


class SummaryModel:
    def __init__(self, budget):
        self.calls, self.budget = [], budget

    def invoke(self, messages, **kwargs):
        self.budget.model()
        payload = json.loads(messages[-1].content)
        self.calls.append((kwargs["name"], payload))
        rows = payload.get("material", payload.get("evidence", []))
        ids = list(dict.fromkeys([rows[0]["evidence_id"], rows[-1]["evidence_id"]]))
        return AnswerDraft(supported=True, answer="Summary based on all supplied material.", source_ids=ids)


@pytest.fixture
def setup_tools(monkeypatch, make_record, chat_memory):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "unit-pinecone-key")
    video = make_record()
    settings = AgentSettings()
    budget = Budget(settings)
    model = SummaryModel(budget)
    ledger = Evidence(video.video_id)
    rag = RagSettings.from_env()
    tools = {t.name: t for t in make_tools(video, ledger, settings, rag, budget, model)}
    return video, settings, budget, model, ledger, rag, tools


@pytest.mark.parametrize("value,expected", [("02:30", 150), ("01:02:15", 3735), ("5 minutes", 300), ("5min", 300), ("15 seconds", 15), ("1.5h", 5400), (12.25, 12.25)])
def test_timestamp_formats(value, expected):
    assert seconds(value) == expected


@pytest.mark.parametrize("value", [-1, True, "-2", "02:60", "01:99:10", "not-a-time", float("inf"), float("nan")])
def test_invalid_timestamps(value):
    with pytest.raises(ValueError):
        seconds(value)


def test_search_reuses_validated_video_retrieval(setup_tools, monkeypatch):
    video, settings, budget, model, ledger, rag, tools = setup_tools
    called = []
    def retrieve(current, query):
        called.append((current.video_id, query))
        return [Document(page_content="Actual caption.", metadata={"chunk_index": 4, "similarity_score": .9, "start_seconds": .25, "end_seconds": 4.75})]
    monkeypatch.setattr(tool_module, "retrieve_evidence", retrieve)
    result = tools["search_transcript"].invoke({"query": "neural networks"})
    assert called == [(video.video_id, "neural networks")]
    assert result["results"][0]["video_id"] == video.video_id
    assert result["results"][0]["similarity_score"] == .9
    assert ledger.sources([0])[0].start_seconds == .25
    with pytest.raises(ValidationError):
        tools["search_transcript"].invoke({"query": "topic", "video_id": "abcdefghijk"})


def test_time_lookup_is_chronological_and_never_uses_pinecone(setup_tools, monkeypatch):
    video, settings, budget, model, ledger, rag, tools = setup_tools
    monkeypatch.setattr(tool_module, "retrieve_evidence", lambda *args: pytest.fail("Time lookup must not search Pinecone."))
    result = tools["get_transcript_segment"].invoke({"start_seconds": "00:01", "end_seconds": "00:06"})
    assert [s["start_seconds"] for s in result["results"]] == [.25, 4.0]
    assert [s["end_seconds"] for s in result["results"]] == [4.75, 6.125]
    assert tools["get_transcript_segment"].invoke({"start_seconds": "02:30"})["empty"]
    with pytest.raises(ApiException) as caught:
        tools["get_transcript_segment"].invoke({"start_seconds": 6, "end_seconds": 1})
    assert caught.value.code == "INVALID_TIME_RANGE"
    with pytest.raises(ApiException):
        tools["get_transcript_segment"].invoke({"start_seconds": 0, "end_seconds": 1000})
    with pytest.raises(ValidationError):
        tools["get_transcript_segment"].invoke({"start_seconds": 0, "video_id": "abcdefghijk"})


def test_short_summary_is_grounded_and_persistently_cached(setup_tools, chat_memory):
    video, settings, budget, model, ledger, rag, tools = setup_tools
    first = tools["summarize_video"].invoke({"detail": "brief"})
    assert first["coverage"] == "complete" and first["results"]
    count = len(model.calls)
    second = tools["summarize_video"].invoke({"detail": "brief"})
    assert second["cached"] and len(model.calls) == count
    assert first["summary"] == second["summary"]
    assert chat_memory.summaries


def test_hierarchical_summary_covers_later_batches(setup_tools, make_record):
    _, settings, _, _, _, rag, _ = setup_tools
    settings = replace(settings, summary_batch_chars=1100, summary_max_batches=5, max_model_calls=10)
    budget = Budget(settings)
    model = SummaryModel(budget)
    video = make_record(transcript=[TranscriptSegment(start_seconds=i, end_seconds=i+1, text=f"Caption {i}. " + "actual material " * 12) for i in range(12)])
    result = summarization.summarize(video, Evidence(video.video_id), settings, rag, budget, model)
    assert result["batches"] >= 2 and result["coverage"] == "complete"
    assert any(name == "summary.synthesis" for name, _ in model.calls)
    text = " ".join(row["text"] for name, payload in model.calls if name == "summary.map" for row in payload["material"])
    assert "Caption 0." in text and "Caption 11." in text


def test_long_summary_fails_before_partial_model_work(setup_tools, make_record):
    _, settings, _, _, _, rag, _ = setup_tools
    settings = replace(settings, summary_batch_chars=1000, summary_max_batches=1)
    budget = Budget(settings)
    model = SummaryModel(budget)
    video = make_record(transcript=[TranscriptSegment(start_seconds=i, end_seconds=i+1, text="actual words " * 100) for i in range(10)])
    with pytest.raises(ApiException) as caught:
        summarization.summarize(video, Evidence(video.video_id), settings, rag, budget, model)
    assert caught.value.code == "SUMMARY_TOO_LONG"
    assert not model.calls


def test_range_summary_does_not_include_outside_captions(setup_tools, make_record):
    _, settings, _, _, _, rag, _ = setup_tools
    video = make_record(transcript=[TranscriptSegment(start_seconds=0, end_seconds=1, text="Outside first."), TranscriptSegment(start_seconds=150, end_seconds=160, text="Inside requested interval."), TranscriptSegment(start_seconds=900, end_seconds=910, text="Outside last.")])
    budget = Budget(settings)
    model = SummaryModel(budget)
    result = summarization.summarize(video, Evidence(video.video_id), settings, rag, budget, model, start=140, end=170)
    text = model.calls[0][1]["material"][0]["text"]
    assert "Inside requested" in text and "Outside" not in text
    assert result["results"][0]["start_seconds"] == 150


def test_empty_transcript_summary_has_no_model_calls(setup_tools):
    video, settings, budget, model, ledger, rag, _ = setup_tools
    result = summarization.summarize(video.model_copy(update={"transcript": []}), ledger, settings, rag, budget, model)
    assert result["empty"] and result["results"] == [] and not model.calls
