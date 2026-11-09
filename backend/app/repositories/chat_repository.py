"""Atomic Supabase session leases/exchanges and bounded chronological history."""
from dataclasses import dataclass
from uuid import UUID

from postgrest.exceptions import APIError
from app.db.supabase_client import get_supabase_client
from app.schemas.error import ApiException


def execute(query):
    try:
        return query.execute().data
    except APIError as error:
        if getattr(error, "code", "") in {"PGRST202", "PGRST205", "42P01", "42883"}:
            raise ApiException(500, "MEMORY_NOT_CONFIGURED", "Apply backend/migrations/002_chat_memory_and_summaries.sql to Supabase.") from None
        raise


@dataclass(frozen=True)
class Claim:
    session_id: UUID
    token: UUID
    revision: int
    fresh: bool


def claim_session(session_id, video_id, seconds=75):
    with get_supabase_client() as client:
        row = execute(client.rpc("tubeinsight_chat_claim", {"p_session_id": str(session_id) if session_id else None, "p_video_id": video_id, "p_lease_seconds": min(300, max(75, seconds))}))
    if row.get("status") == "not_found":
        raise ApiException(404, "CONVERSATION_NOT_FOUND", "Conversation not found for this video.")
    if row.get("status") == "busy":
        raise ApiException(409, "CONVERSATION_BUSY", "Another message is being processed in this conversation. Retry shortly.")
    if row.get("status") != "claimed":
        raise ApiException(503, "DATABASE_UNAVAILABLE", "Conversation storage did not confirm the session.")
    return Claim(UUID(row["session_id"]), UUID(row["token"]), row["revision"], row["fresh"])


def get_history(claim, max_messages, max_chars):
    with get_supabase_client() as client:
        rows = execute(client.table("chat_messages").select("role,content,sequence_number").eq("session_id", str(claim.session_id)).order("sequence_number", desc=True).limit(max_messages))
    selected, size = [], 0
    for row in rows:
        if row["role"] not in {"user", "assistant"}:
            raise ApiException(502, "INVALID_CHAT_HISTORY", "The saved conversation is invalid.")
        if size + len(row["content"]) > max_chars:
            break
        selected.append({"role": row["role"], "content": row["content"]})
        size += len(row["content"])
    selected.reverse()
    while selected and selected[0]["role"] != "user":
        selected.pop(0)
    return selected


def finish_exchange(claim, question, answer):
    with get_supabase_client() as client:
        result = execute(client.rpc("tubeinsight_chat_finish", {"p_session_id": str(claim.session_id), "p_token": str(claim.token), "p_revision": claim.revision, "p_question": question, "p_answer": answer}))
    if result.get("status") != "completed":
        raise ApiException(409, "CONVERSATION_BUSY", "The conversation changed while this message was processed. Please retry.")


def release_session(claim):
    with get_supabase_client() as client:
        execute(client.rpc("tubeinsight_chat_release", {"p_session_id": str(claim.session_id), "p_token": str(claim.token), "p_discard_new": claim.fresh}))


def get_summary(key, video_id):
    with get_supabase_client() as client:
        rows = execute(client.table("video_summary_cache").select("result").eq("cache_key", key).eq("video_id", video_id).limit(1))
    return rows[0]["result"] if rows else None


def save_summary(key, video_id, result):
    with get_supabase_client() as client:
        rows = execute(client.table("video_summary_cache").upsert({"cache_key": key, "video_id": video_id, "result": result}, on_conflict="cache_key"))
    if not rows:
        raise ApiException(503, "DATABASE_UNAVAILABLE", "Summary storage did not confirm the saved result.")
