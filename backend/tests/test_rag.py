"""RAG semantics over real LangChain components with mocked external calls."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from app.rag.document_store import DocumentVectorStore

from app.rag import answering, indexing, providers
from app.rag.answering import AnswerDraft, INSUFFICIENT_EVIDENCE
from app.rag.chunking import build_plan
from app.rag.settings import RagSettings
from app.schemas.error import ApiException
from app.schemas.video import TranscriptSegment


class FakeIndex:
    def __init__(self):
        self.rows = {}
        self.upserts = []
        self.queries = []
        self.override_matches = None
        self.embedding = SimpleNamespace(documents=[], queries=[])

    def fetch(self, ids, namespace, **kwargs):
        return {"records": {ident: {"metadata": {k: deepcopy(v) for k, v in self.rows[(namespace, ident)].items() if k not in {"_id", "chunk_text"}}} for ident in ids if (namespace, ident) in self.rows}}

    def upsert_documents(self, documents, namespace):
        self.upserts.append((namespace, deepcopy(documents)))
        if documents[0]["_id"] != indexing.MANIFEST_ID:
            self.embedding.documents.append([doc["chunk_text"] for doc in documents])
        for row in documents:
            self.rows[(namespace, row["_id"])] = deepcopy(row)
        return {"upserted_count": len(documents)}

    def search_documents(self, query, namespace, top_k, filter):
        self.embedding.queries.append(query)
        self.queries.append({"namespace": namespace, "filter": filter, "top_k": top_k})
        if self.override_matches is not None:
            return {"matches": deepcopy(self.override_matches)}
        rows = [dict(row, _score=.9)
                for (ns, ident), row in self.rows.items()
                if ns == namespace and row.get("kind") == "chunk"
                and all(row.get(key) == condition["$eq"] for key, condition in filter.items())]
        return {"matches": rows[:top_k]}


@pytest.fixture
def rag(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "unit-pinecone-key")
    index = FakeIndex()
    embedding = index.embedding

    @contextmanager
    def open_index(settings):
        yield index

    @contextmanager
    def open_store(index, settings, namespace):
        yield DocumentVectorStore(index=index, namespace=namespace, embedding_field=settings.embedding_field)

    for module in [indexing, answering]:
        monkeypatch.setattr(module, "open_index", open_index)
        monkeypatch.setattr(module, "open_vector_store", open_store)
    generate = Mock(side_effect=lambda settings, question, docs: AnswerDraft(supported=True, answer="Answer based on video evidence.", source_ids=[docs[0].metadata["chunk_index"]]))
    monkeypatch.setattr(answering, "generate_answer", generate)
    return SimpleNamespace(index=index, embedding=embedding, generate=generate, settings=RagSettings.from_env())


def test_chunk_spans_preserve_original_timestamps_and_metadata(make_record, rag):
    segments = [TranscriptSegment(start_seconds=i * 2.25, end_seconds=i * 2.25 + 3, text=f"Sentence {i}. " + "actual words " * 8) for i in range(40)]
    video = make_record(transcript=segments)
    plan = build_plan(video, rag.settings)
    text = "\n".join(s.text for s in segments)
    assert len(plan.documents) > 1
    for i, doc in enumerate(plan.documents):
        meta = doc.metadata
        assert meta["video_id"] == video.video_id and meta["chunk_index"] == i
        assert doc.page_content == text[meta["start_char"]:meta["end_char"]] == meta["text"]
        contributing = segments[meta["source_segment_start"]:meta["source_segment_end"] + 1]
        assert meta["start_seconds"] == min(s.start_seconds for s in contributing)
        assert meta["end_seconds"] == max(s.end_seconds for s in contributing)
        assert len(doc.page_content) <= rag.settings.chunk_size
    assert plan.documents[0].metadata["start_seconds"] == 0
    assert plan.documents[-1].metadata["end_seconds"] == segments[-1].end_seconds


@pytest.mark.parametrize("text", ["repeat " * 900, "字" * 5000, "a" * 5000, " same. same. " * 300])
def test_long_single_caption_and_repeated_text_are_traceable(make_record, rag, text):
    video = make_record(transcript=[TranscriptSegment(start_seconds=1.25, end_seconds=5.75, text=text)])
    plan = build_plan(video, rag.settings)
    assert len(plan.documents) > 1
    for doc in plan.documents:
        assert doc.page_content == text[doc.metadata["start_char"]:doc.metadata["end_char"]]
        assert (doc.metadata["start_seconds"], doc.metadata["end_seconds"]) == (1.25, 5.75)


def test_overlap_blank_and_out_of_order_captions_do_not_invent_times(make_record, rag):
    video = make_record(transcript=[
        TranscriptSegment(start_seconds=8.5, end_seconds=10, text="First actual text."),
        TranscriptSegment(start_seconds=1, end_seconds=20, text="  "),
        TranscriptSegment(start_seconds=3.5, end_seconds=11, text="Second overlapping text."),
    ])
    doc = build_plan(video, rag.settings).documents[0]
    assert doc.metadata["start_seconds"] == 3.5 and doc.metadata["end_seconds"] == 11
    assert doc.page_content == "First actual text.\nSecond overlapping text."


def test_indexing_is_batched_and_idempotent(make_record, rag, monkeypatch):
    monkeypatch.setenv("RAG_EMBED_BATCH_SIZE", "2")
    video = make_record(transcript=[TranscriptSegment(start_seconds=i, end_seconds=i+1, text=(f"Caption {i}. " * 80)) for i in range(10)])
    first = indexing.ensure_indexed(video)
    rows = deepcopy(rag.index.rows)
    second = indexing.ensure_indexed(video)
    assert not first.cached and second.cached
    assert rag.index.rows == rows
    assert all(len(batch) <= 2 for batch in rag.embedding.documents)
    assert sum(map(len, rag.embedding.documents)) == first.chunks
    assert len(rows) == first.chunks + 1  # Separate completion manifest.


def test_changed_transcript_or_embedding_configuration_gets_new_namespace(make_record, rag):
    original = make_record()
    indexing.ensure_indexed(original)
    before = build_plan(original, rag.settings)
    updated = make_record(language="de")
    after = build_plan(updated, rag.settings)
    assert before.namespace != after.namespace
    assert before.namespace != build_plan(original, replace(rag.settings, chunk_overlap=100)).namespace
    assert before.namespace != build_plan(original, replace(rag.settings, embedding_model="text-embedding-3-large")).namespace
    indexing.ensure_indexed(updated)
    assert any(namespace == before.namespace for namespace, ident in rag.index.rows)
    assert any(namespace == after.namespace for namespace, ident in rag.index.rows)


def test_failed_indexing_has_no_ready_marker_and_resumes(make_record, rag, monkeypatch):
    video = make_record()
    original = rag.index.upsert_documents

    def fail(documents, namespace):
        if documents[0]["_id"] == indexing.MANIFEST_ID:
            raise ApiException(503, "RAG_UNAVAILABLE", "Unavailable.")
        return original(documents=documents, namespace=namespace)

    monkeypatch.setattr(rag.index, "upsert_documents", fail)
    with pytest.raises(ApiException):
        indexing.ensure_indexed(video)
    count = len(rag.embedding.documents)
    monkeypatch.setattr(rag.index, "upsert_documents", original)
    assert not indexing.ensure_indexed(video).cached
    assert len(rag.embedding.documents) == count  # Resume stored batches.


def test_unindexed_chat_has_no_embedding_or_model_calls(make_record, rag):
    with pytest.raises(ApiException) as caught:
        answering.answer_question(make_record(), "What does the video say?")
    assert caught.value.code == "VIDEO_NOT_INDEXED"
    assert not rag.embedding.documents and not rag.embedding.queries
    rag.generate.assert_not_called()


def test_rag_returns_actual_sources_and_does_not_reembed_video(make_record, rag):
    video = make_record()
    indexing.ensure_indexed(video)
    count = len(rag.embedding.documents)
    answer, sources = answering.answer_question(video, "What is the first sentence?")
    doc = build_plan(video, rag.settings).documents[0]
    assert answer == "Answer based on video evidence."
    assert sources[0].text == doc.page_content
    assert (sources[0].start_seconds, sources[0].end_seconds) == (.25, 6.125)
    assert len(rag.embedding.documents) == count
    query = rag.index.queries[0]
    assert query["top_k"] == 4
    assert query["filter"]["video_id"] == {"$eq": video.video_id}
    assert query["namespace"] == build_plan(video, rag.settings).namespace


@pytest.mark.parametrize("tamper", ["video", "text", "timestamp", "fingerprint", "index"])
def test_invalid_or_cross_video_sources_never_reach_model(make_record, rag, tamper):
    video = make_record()
    indexing.ensure_indexed(video)
    doc = build_plan(video, rag.settings).documents[0]
    metadata = deepcopy(doc.metadata)
    if tamper == "video": metadata["video_id"] = "abcdefghijk"
    if tamper == "text": metadata["text"] = "Malicious fabricated quote."
    if tamper == "timestamp": metadata["start_seconds"] = 1234
    if tamper == "fingerprint": metadata["fingerprint"] = "old-transcript"
    if tamper == "index": metadata["chunk_index"] = .5
    rag.index.override_matches = [dict(metadata, _id="malicious", _score=.99, chunk_text=metadata["text"])]
    assert answering.answer_question(video, "What does it say?") == (INSUFFICIENT_EVIDENCE, [])
    rag.generate.assert_not_called()


def test_unrelated_videos_have_separate_namespaces(make_record, rag):
    first, second = make_record(), make_record("abcdefghijk")
    indexing.ensure_indexed(first)
    indexing.ensure_indexed(second)
    answering.answer_question(second, "What does the second video say?")
    documents = rag.generate.call_args.args[2]
    assert all(doc.metadata["video_id"] == second.video_id for doc in documents)
    assert rag.index.queries[-1]["namespace"] != build_plan(first, rag.settings).namespace


def test_model_abstention_has_no_invented_sources(make_record, rag):
    video = make_record()
    indexing.ensure_indexed(video)
    rag.generate.side_effect = None
    rag.generate.return_value = AnswerDraft(supported=False, answer="Untrusted invented answer.", source_ids=[999])
    assert answering.answer_question(video, "What is the speaker's bank password?") == (INSUFFICIENT_EVIDENCE, [])


def test_invalid_model_citations_are_an_error(make_record, rag):
    video = make_record()
    indexing.ensure_indexed(video)
    rag.generate.side_effect = None
    rag.generate.return_value = AnswerDraft(supported=True, answer="Invented answer.", source_ids=[999])
    with pytest.raises(ApiException) as caught:
        answering.answer_question(video, "What is discussed?")
    assert caught.value.code == "RAG_RESPONSE_INVALID"


def test_no_relevant_matches_skips_model(make_record, rag):
    video = make_record()
    indexing.ensure_indexed(video)
    rag.index.override_matches = []
    assert answering.answer_question(video, "Unrelated question") == (INSUFFICIENT_EVIDENCE, [])
    rag.generate.assert_not_called()


def test_float32_storage_rounding_returns_exact_original_times(make_record, rag, monkeypatch):
    import struct
    original = rag.index.upsert_documents

    def rounded(documents, namespace):
        documents = deepcopy(documents)
        for row in documents:
            for key in ["start_seconds", "end_seconds"]:
                if key in row:
                    row[key] = struct.unpack("f", struct.pack("f", row[key]))[0]
        return original(documents, namespace)

    monkeypatch.setattr(rag.index, "upsert_documents", rounded)
    video = make_record(transcript=[TranscriptSegment(start_seconds=1.123456789, end_seconds=6.987654321, text="Actual saved caption.")])
    indexing.ensure_indexed(video)
    assert indexing.ensure_indexed(video).cached
    _, sources = answering.answer_question(video, "What is said?")
    assert sources[0].start_seconds == 1.123456789
    assert sources[0].end_seconds == 6.987654321


@pytest.mark.parametrize("provider_error", [TimeoutError("secret key"), RuntimeError("secret key")])
def test_provider_error_mapping_redacts_private_details(caplog, provider_error):
    with pytest.raises(ApiException) as caught:
        with providers.provider_errors("OpenAI"):
            raise provider_error
    assert caught.value.code in {"RAG_TIMEOUT", "RAG_UNAVAILABLE"}
    assert "secret key" not in caught.value.message + caplog.text


@pytest.mark.parametrize("name,value", [("OPENAI_API_KEY", ""), ("PINECONE_API_KEY", ""), ("RAG_TOP_K", "0"), ("RAG_MIN_SCORE", "nan"), ("RAG_CHUNK_OVERLAP", "1000"), ("PINECONE_EMBEDDING_MODEL", "unknown")])
def test_bad_settings_fail_safely(rag, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ApiException) as caught:
        RagSettings.from_env()
    assert caught.value.code == "CONFIGURATION_ERROR"
    assert "unit-openai-key" not in caught.value.message


def test_rag_keys_never_appear_in_settings_repr(rag):
    assert "unit-openai-key" not in repr(rag.settings)
    assert "unit-pinecone-key" not in repr(rag.settings)
