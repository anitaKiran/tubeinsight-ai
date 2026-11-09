"""Idempotent local indexing, versioned namespaces, and completion manifests."""

from dataclasses import dataclass
import logging
import time

from langsmith import tracing_context

from app.rag.chunking import build_plan, ChunkPlan
from app.rag.providers import open_index, open_vector_store, provider_errors
from app.rag.settings import RagSettings
from app.rag.metadata import metadata_matches
from app.runtime import require_local_extraction
from app.schemas.error import ApiException
from app.schemas.stored_video import StoredVideo

logger = logging.getLogger(__name__)
MANIFEST_ID = "__ready__"


def _records(response):
    return response.get("records", {}) if isinstance(response, dict) else response.records


def _metadata(vector):
    return vector.get("metadata", {}) if isinstance(vector, dict) else vector.metadata


def is_indexed(index, plan: ChunkPlan) -> bool:
    vectors = _records(index.fetch(ids=[MANIFEST_ID], namespace=plan.namespace))
    marker = vectors.get(MANIFEST_ID)
    if marker is None:
        return False
    metadata = _metadata(marker)
    return (
        metadata.get("kind") == "manifest" and metadata.get("video_id") == plan.video_id
        and metadata.get("fingerprint") == plan.fingerprint
        and metadata.get("chunk_count") == len(plan.documents)
    )


def require_indexed(index, plan: ChunkPlan):
    if not is_indexed(index, plan):
        raise ApiException(409, "VIDEO_NOT_INDEXED", "This saved transcript has not been indexed. Index it locally before asking questions.")


@dataclass(frozen=True)
class IndexingResult:
    video_id: str
    chunks: int
    cached: bool


def ensure_indexed(video: StoredVideo, *, force: bool = False) -> IndexingResult:
    require_local_extraction()  # Neither chat nor production may index a video.
    settings = RagSettings.from_env()
    started = time.monotonic()
    deadline = started + settings.index_budget
    plan = build_plan(video, settings)
    if not plan.documents or len(plan.documents) > settings.max_chunks:
        raise ApiException(422, "INDEXING_LIMIT_EXCEEDED", "Transcript exceeds RAG_MAX_CHUNKS. Adjust local indexing limits before retrying.")

    def check_deadline():
        if time.monotonic() >= deadline:
            raise ApiException(504, "INDEXING_TIMEOUT", "Transcript is saved, but indexing reached its time limit. Retry local processing or use the indexing CLI.")

    with tracing_context(enabled=False), open_index(settings) as index:
        if is_indexed(index, plan) and not force:
            return IndexingResult(video.video_id, len(plan.documents), True)
        with open_vector_store(index, settings, plan.namespace) as store:
            for offset in range(0, len(plan.ids), settings.batch_size):
                check_deadline()
                ids = plan.ids[offset:offset + settings.batch_size]
                docs = plan.documents[offset:offset + settings.batch_size]
                existing = _records(index.fetch(ids=ids, namespace=plan.namespace))
                # Resume interrupted runs without paying for successful batches again.
                missing = [i for i, ident in enumerate(ids) if force or ident not in existing or not metadata_matches(_metadata(existing[ident]), docs[i].metadata)]
                if missing:
                    with provider_errors("Pinecone"):
                        store.add_texts(
                            texts=[docs[i].page_content for i in missing],
                            metadatas=[dict(docs[i].metadata) for i in missing],
                            ids=[ids[i] for i in missing], namespace=plan.namespace,
                            batch_size=settings.batch_size, embedding_chunk_size=settings.batch_size,
                            async_req=False,
                        )
                # Pinecone is eventually consistent. Confirm each batch before the
                # ready marker. A failed/partial reindex never exposes old chunks.
                for attempt in range(4):
                    check_deadline()
                    visible = _records(index.fetch(ids=ids, namespace=plan.namespace))
                    if all(ident in visible and metadata_matches(_metadata(visible[ident]), doc.metadata) for ident, doc in zip(ids, docs)):
                        break
                    if attempt == 3:
                        raise ApiException(503, "INDEXING_PENDING", "Transcript is saved; Pinecone has not confirmed every chunk yet. Retry indexing shortly.")
                    time.sleep(1.0 * (attempt + 1))
                logger.info("Video indexing progress: video=%s chunks=%s/%s", video.video_id, offset + len(ids), len(plan.ids))
        check_deadline()
        index.upsert_documents(documents=[{
            "_id": MANIFEST_ID, settings.embedding_field: "Transcript indexing completion marker.",
            "kind": "manifest", "video_id": video.video_id, "fingerprint": plan.fingerprint, "chunk_count": len(plan.ids),
        }], namespace=plan.namespace)
        for attempt in range(4):
            check_deadline()
            if is_indexed(index, plan):
                return IndexingResult(video.video_id, len(plan.documents), False)
            if attempt < 3:
                time.sleep(1.0 * (attempt + 1))
        raise ApiException(503, "INDEXING_PENDING", "Transcript is saved; Pinecone indexing confirmation is pending. Try again shortly.")
