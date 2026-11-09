"""Real Supabase query/RPC builders over mocked HTTPS, no live credentials."""
import json
from uuid import uuid4

import httpx
import pytest

from app.db import supabase_client
from app.repositories import chat_repository as repo
from app.schemas.error import ApiException


@pytest.fixture
def memory_sdk(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://unit.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_unit-test-only")
    sid, token = uuid4(), uuid4()
    state = {"status": "claimed", "session_id": str(sid), "token": str(token), "revision": 0, "fresh": True}
    calls = []
    def handle(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request, body))
        if state.get("missing"):
            return httpx.Response(404, json={"code": "PGRST202", "message": "private missing function details"})
        if request.url.path.endswith("tubeinsight_chat_claim"):
            return httpx.Response(200, json=state)
        if request.url.path.endswith("tubeinsight_chat_finish"):
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("tubeinsight_chat_release"):
            return httpx.Response(200, json={"status": "released"})
        if request.url.path.endswith("chat_messages"):
            return httpx.Response(200, json=[
                {"role": "assistant", "content": "Prior answer", "sequence_number": 3},
                {"role": "user", "content": "Prior question", "sequence_number": 2},
            ])
        if request.url.path.endswith("video_summary_cache"):
            if request.method == "POST":
                return httpx.Response(201, json=[body])
            return httpx.Response(200, json=[])
        raise AssertionError("Unexpected repository request")
    original = httpx.Client
    monkeypatch.setattr(supabase_client.httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    return state, calls


def test_claim_history_and_atomic_exchange_rpc(memory_sdk):
    state, calls = memory_sdk
    claim = repo.claim_session(None, "dQw4w9WgXcQ")
    assert str(claim.session_id) == state["session_id"]
    history = repo.get_history(claim, 2, 1000)
    assert [r["role"] for r in history] == ["user", "assistant"]
    repo.finish_exchange(claim, "New question", "New grounded answer")
    repo.release_session(claim)
    assert calls[0][1]["p_video_id"] == "dQw4w9WgXcQ"
    assert calls[1][0].url.params["order"] == "sequence_number.desc"
    assert calls[1][0].url.params["limit"] == "2"
    finish = calls[2][1]
    assert finish["p_question"] == "New question" and finish["p_answer"] == "New grounded answer"
    assert finish["p_token"] == state["token"] and finish["p_revision"] == 0
    assert "Authorization" not in calls[0][0].headers


@pytest.mark.parametrize("status,code", [("busy", "CONVERSATION_BUSY"), ("not_found", "CONVERSATION_NOT_FOUND")])
def test_claim_statuses_are_safe_api_errors(memory_sdk, status, code):
    state, calls = memory_sdk
    state["status"] = status
    with pytest.raises(ApiException) as caught:
        repo.claim_session(uuid4(), "dQw4w9WgXcQ")
    assert caught.value.code == code


def test_missing_migration_has_explicit_setup_error(memory_sdk):
    state, calls = memory_sdk
    state["missing"] = True
    with pytest.raises(ApiException) as caught:
        repo.claim_session(None, "dQw4w9WgXcQ")
    assert caught.value.code == "MEMORY_NOT_CONFIGURED"
    assert "private missing function" not in caught.value.message


def test_summary_cache_remains_video_scoped(memory_sdk):
    state, calls = memory_sdk
    assert repo.get_summary("a" * 64, "dQw4w9WgXcQ") is None
    repo.save_summary("a" * 64, "dQw4w9WgXcQ", {"answer": "Grounded summary", "sources": []})
    assert calls[0][0].url.params["video_id"] == "eq.dQw4w9WgXcQ"
    assert calls[1][1]["video_id"] == "dQw4w9WgXcQ"
