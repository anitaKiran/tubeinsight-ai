"""Character spans map LangChain chunks back to exact saved caption segments."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import hashlib
import json

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.settings import RagSettings
from app.schemas.stored_video import StoredVideo

CHUNK_VERSION = "caption-spans-v1"


@dataclass(frozen=True)
class ChunkPlan:
    video_id: str
    fingerprint: str
    namespace: str
    documents: list[Document]
    ids: list[str]


def build_plan(video: StoredVideo, settings: RagSettings) -> ChunkPlan:
    payload = {
        "video_id": video.video_id, "language": video.language,
        "transcript": [segment.model_dump() for segment in video.transcript],
        "model": settings.embedding_model, "field": settings.embedding_field, "dimensions": settings.dimensions,
        "size": settings.chunk_size, "overlap": settings.chunk_overlap, "version": CHUNK_VERSION,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    texts, starts, ends, indices = [], [], [], []
    position = 0
    for index, segment in enumerate(video.transcript):
        if not segment.text.strip():
            continue
        if texts:
            position += 1  # The exact newline separator below.
        starts.append(position)
        texts.append(segment.text)
        position += len(segment.text)
        ends.append(position)
        indices.append(index)
    text = "\n".join(texts)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
        add_start_index=True, strip_whitespace=False,
    )
    documents = []
    for raw in splitter.create_documents([text]):
        if not raw.page_content.strip():
            continue
        start = raw.metadata["start_index"]
        end = start + len(raw.page_content)
        if start < 0 or text[start:end] != raw.page_content:
            raise ValueError("Chunk source span could not be verified.")
        left, right = bisect_right(ends, start), bisect_left(starts, end)
        contributing = [video.transcript[i] for i in indices[left:right]]
        if not contributing:
            continue
        chunk_index = len(documents)
        documents.append(Document(page_content=raw.page_content, metadata={
            "kind": "chunk", "video_id": video.video_id, "fingerprint": fingerprint,
            "chunk_index": chunk_index, "text": raw.page_content,
            "start_seconds": min(s.start_seconds for s in contributing),
            "end_seconds": max(s.end_seconds for s in contributing),
            "source_segment_start": indices[left], "source_segment_end": indices[right - 1],
            "start_char": start, "end_char": end,
        }))
    return ChunkPlan(
        video_id=video.video_id, fingerprint=fingerprint,
        namespace=f"video-{video.video_id}-{fingerprint}", documents=documents,
        ids=[f"{video.video_id}:{fingerprint}:{index}" for index in range(len(documents))],
    )
