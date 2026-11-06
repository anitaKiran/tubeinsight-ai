"""Validated server-only RAG configuration. Never include key values in errors."""

from dataclasses import dataclass, field
import math
import os
import re

from app.schemas.error import ApiException


@dataclass(frozen=True)
class RagSettings:
    openai_key: str = field(repr=False)
    pinecone_key: str = field(repr=False)
    chat_model: str = "gpt-6-luna"
    embedding_model: str = "llama-text-embed-v2"
    embedding_field: str = "chunk_text"
    index_name: str = "tubechunks"
    dimensions: int = 1024
    chunk_size: int = 1000
    chunk_overlap: int = 180
    batch_size: int = 32
    top_k: int = 4
    min_score: float = .25
    api_timeout: float = 10
    index_budget: float = 90
    max_chunks: int = 2000

    @classmethod
    def from_env(cls):
        def required(name):
            value = os.getenv(name, "").strip()
            if not value or any(c.isspace() for c in value):
                raise ApiException(500, "CONFIGURATION_ERROR", f"Configure {name} on the backend.")
            return value

        def number(name, default, low, high, integer=False):
            try:
                value = int(os.getenv(name, str(default))) if integer else float(os.getenv(name, str(default)))
                if not math.isfinite(value) or not low <= value <= high:
                    raise ValueError
                return value
            except ValueError:
                raise ApiException(500, "CONFIGURATION_ERROR", f"{name} must be between {low} and {high}.") from None

        size = number("RAG_CHUNK_SIZE", 1000, 200, 2000, True)
        overlap = number("RAG_CHUNK_OVERLAP", 180, 0, size - 1, True)
        embedding = os.getenv("PINECONE_EMBEDDING_MODEL", "llama-text-embed-v2").strip()
        if embedding != "llama-text-embed-v2":
            raise ApiException(500, "CONFIGURATION_ERROR", "PINECONE_EMBEDDING_MODEL must match the index model llama-text-embed-v2.")
        name = required("PINECONE_INDEX_NAME")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,44}", name):
            raise ApiException(500, "CONFIGURATION_ERROR", "PINECONE_INDEX_NAME must be a valid index name.")
        return cls(
            openai_key=required("OPENAI_API_KEY"), pinecone_key=required("PINECONE_API_KEY"),
            chat_model=required("OPENAI_CHAT_MODEL"), embedding_model=embedding, index_name=name,
            dimensions=number("PINECONE_EMBEDDING_DIMENSIONS", 1024, 128, 2048, True),
            embedding_field=required("PINECONE_EMBEDDING_FIELD"),
            chunk_size=size, chunk_overlap=overlap,
            batch_size=number("RAG_EMBED_BATCH_SIZE", 32, 1, 64, True),
            top_k=number("RAG_TOP_K", 4, 1, 10, True),
            min_score=number("RAG_MIN_SCORE", .25, -1, 1),
            api_timeout=number("RAG_API_TIMEOUT_SECONDS", 10, 1, 20),
            index_budget=number("RAG_INDEX_TIMEOUT_SECONDS", 90, 5, 120),
            max_chunks=number("RAG_MAX_CHUNKS", 2000, 1, 10000, True),
        )
