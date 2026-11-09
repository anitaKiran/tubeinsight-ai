"""Bounded provider clients, current document APIs, and safe error mapping."""

from contextlib import contextmanager
import logging
from urllib.parse import quote

import httpx

from app.rag.settings import RagSettings
from app.schemas.error import ApiException

logger = logging.getLogger(__name__)


@contextmanager
def provider_errors(service: str):
    try:
        yield
    except ApiException:
        raise
    except Exception as error:
        # Never log provider exceptions, headers, request bodies, or signed URLs.
        logger.warning("RAG provider failure: service=%s type=%s", service, type(error).__name__)
        status = getattr(error, "status_code", getattr(error, "status", None))
        if status == 429 or "RateLimit" in type(error).__name__:
            raise ApiException(429, "RAG_RATE_LIMITED", f"{service} is rate limiting requests. Try again later.") from None
        if "Timeout" in type(error).__name__ or isinstance(error, TimeoutError):
            raise ApiException(504, "RAG_TIMEOUT", f"{service} timed out. Try again later.") from None
        if status in {401, 403, 404}:
            raise ApiException(500, "CONFIGURATION_ERROR", f"Check backend {service} credentials, model, and resource access.") from None
        raise ApiException(503, "RAG_UNAVAILABLE", f"{service} is unavailable. Try again later.") from None


def describe_index(settings: RagSettings) -> dict:
    with provider_errors("Pinecone"):
        with httpx.Client(timeout=httpx.Timeout(settings.api_timeout, connect=3), follow_redirects=False, trust_env=False) as client:
            response = client.get(
                f"https://api.pinecone.io/indexes/{settings.index_name}",
                headers={"Api-Key": settings.pinecone_key, "X-Pinecone-API-Version": "2026-07"},
            )
            if response.status_code == 404:
                raise ApiException(500, "PINECONE_INDEX_NOT_FOUND", "Configure an existing Pinecone document index with a matching embedded-text field.")
            _check_response(response)
            description = response.json()
    field = description.get("schema", {}).get("fields", {}).get(settings.embedding_field, {})
    embed = field.get("embed", {})
    if field.get("type") != "string" or embed.get("dimension") != settings.dimensions or embed.get("metric") != "cosine" or embed.get("model") != settings.embedding_model or field.get("store_text") is False:
        raise ApiException(500, "PINECONE_INDEX_INCOMPATIBLE", "Pinecone field, embedding model, dimensions, cosine metric, and stored text must match the backend configuration.")
    if not description.get("status", {}).get("ready"):
        raise ApiException(503, "RAG_UNAVAILABLE", "The Pinecone index is not ready yet.")
    host = description.get("host", "")
    if not isinstance(host, str) or "/" in host or not host.endswith(".pinecone.io"):
        raise ApiException(500, "CONFIGURATION_ERROR", "Pinecone returned an invalid index host.")
    return description


def _check_response(response):
    if response.status_code in {401, 403}:
        raise ApiException(500, "CONFIGURATION_ERROR", "Check backend Pinecone credentials and index access.")
    if response.status_code == 402:
        raise ApiException(500, "CONFIGURATION_ERROR", "Check Pinecone quota and billing settings. No resource was created automatically.")
    if response.status_code == 429:
        raise ApiException(429, "RAG_RATE_LIMITED", "Pinecone is rate limiting requests. Try again later.")
    if response.status_code == 400:
        raise ApiException(500, "PINECONE_INDEX_INCOMPATIBLE", "Pinecone rejected the document request. Check the configured index schema and embedding field.")
    response.raise_for_status()


class DocumentIndex:
    """Bounded 2026-07 documents API, required by the user's existing index.

    langchain-pinecone 0.2.13 pins SDK <8 and only supports the older vectors
    endpoints. This adapter uses Pinecone's documented documents API rather
    than violating its dependency constraints or recreating the user's index.
    """

    def __init__(self, client, host, settings):
        self.client = client
        self.host = host
        self.settings = settings

    def _post(self, operation, namespace, body):
        with provider_errors("Pinecone"):
            response = self.client.post(
                f"https://{self.host}/namespaces/{quote(namespace, safe='')}/documents/{operation}",
                json=body,
            )
            if response.status_code == 404 and operation == "fetch":
                return {"documents": {}}
            _check_response(response)
            return response.json()

    def fetch(self, ids, namespace):
        response = self._post("fetch", namespace, {"ids": ids, "include_fields": ["*"]})
        records = {}
        for ident, row in response.get("documents", {}).items():
            metadata = {key: value for key, value in row.items() if key not in {"_id", self.settings.embedding_field}}
            records[ident] = {"metadata": metadata}
        return {"records": records}

    def upsert_documents(self, documents, namespace):
        return self._post("upsert", namespace, {"documents": documents})

    def search_documents(self, query, namespace, top_k, filter):
        return self._post("search", namespace, {
            "top_k": top_k, "filter": filter, "include_fields": ["*"],
            "score_by": [{"type": "embed", "fields": [self.settings.embedding_field], "query": query}],
        })


@contextmanager
def open_index(settings: RagSettings):
    description = describe_index(settings)
    with httpx.Client(
        timeout=httpx.Timeout(settings.api_timeout, connect=3), follow_redirects=False,
        trust_env=False, headers={"Api-Key": settings.pinecone_key, "X-Pinecone-API-Version": "2026-07"},
    ) as client:
        yield DocumentIndex(client, description["host"], settings)


@contextmanager
def open_vector_store(index, settings: RagSettings, namespace: str):
    from app.rag.document_store import DocumentVectorStore
    yield DocumentVectorStore(index, namespace, settings.embedding_field)

