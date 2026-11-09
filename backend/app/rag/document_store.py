"""Extend LangChain's Pinecone store for current embedded-document indexes."""

from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore


class DocumentVectorStore(PineconeVectorStore):
    """Pinecone generates both passage and query embeddings in the same space.

    This extension replaces the legacy vector transport. No dummy vectors or
    OpenAI embeddings are generated; only the configured field's model is used.
    """

    def __init__(self, index, namespace, embedding_field):
        self._index = index
        self._namespace = namespace
        self.embedding_field = embedding_field

    @property
    def embeddings(self):
        return None  # Server-side embedding; no client embedding object.

    def add_texts(self, texts, metadatas=None, ids=None, namespace=None, batch_size=32, **kwargs):
        texts = list(texts)
        if ids is None or len(ids) != len(texts):
            raise ValueError("Stable document IDs are required for indexing.")
        metadatas = metadatas or [{} for _ in texts]
        documents = [dict(metadata, _id=ident, **{self.embedding_field: text}) for text, metadata, ident in zip(texts, metadatas, ids)]
        for offset in range(0, len(documents), batch_size):
            result = self._index.upsert_documents(documents[offset:offset + batch_size], namespace or self._namespace)
            if result.get("upserted_count") != len(documents[offset:offset + batch_size]):
                raise ValueError("Pinecone did not acknowledge every document.")
        return ids

    def similarity_search_with_score(self, query, k=4, filter=None, namespace=None, **kwargs):
        result = self._index.search_documents(query, namespace or self._namespace, k, filter)
        documents = []
        for row in result.get("matches", []):
            text = row.get(self.embedding_field)
            if not isinstance(text, str):
                continue
            metadata = {key: value for key, value in row.items() if key not in {"_id", "_score", self.embedding_field}}
            documents.append((Document(id=row.get("_id"), page_content=text, metadata=metadata), row.get("_score")))
        return documents
