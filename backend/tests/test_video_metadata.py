"""Provider, persistence and cached repair regressions; zero live credentials."""
from contextlib import contextmanager
import json
from unittest.mock import Mock

import httpx
from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.services import youtube_metadata_service as metadata, metadata_enrichment, video_service, ingestion_service
from app.repositories import video_repository as repo
from app.scripts import backfill_video_metadata as cli
from app.rag.chunking import build_plan
from app.rag.settings import RagSettings

VID="dQw4w9WgXcQ"
URL=f"https://www.youtube.com/watch?v={VID}"
TITLE="Verified public video title — 日本語"


def oembed(**changes):
    return dict({"version":"1.0","type":"video","provider_name":"YouTube","title":TITLE,
        "thumbnail_url":f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"},**changes)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("YOUTUBE_METADATA_ENABLED","true")
    monkeypatch.setenv("YOUTUBE_METADATA_TIMEOUT_SECONDS","4")
    state={"status":200,"body":oembed(),"calls":[],"clients":[]}
    original=httpx.Client
    def respond(request):
        state["calls"].append(request)
        assert request.url.host=="www.youtube.com" and request.url.path=="/oembed"
        assert request.url.params["url"]==URL
        if state.get("timeout"):raise httpx.ReadTimeout("private signed-url details",request=request)
        return httpx.Response(state["status"],json=state["body"],headers=state.get("headers"))
    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client=original(**kwargs,transport=httpx.MockTransport(respond));state["clients"].append(client);return client
    monkeypatch.setattr(metadata.httpx,"Client",factory)
    return state


def test_public_provider_exact_title_and_thumbnail(provider):
    result=metadata.fetch_metadata(VID)
    assert result.title==TITLE and result.thumbnail_url.endswith("hqdefault.jpg")
    assert len(provider["calls"])==1 and provider["clients"][0].is_closed


@pytest.mark.parametrize("invalid",["../etc/passwd","https://evil.example",VID+"x",None])
def test_invalid_id_never_requests(provider,invalid):
    with pytest.raises(Exception):metadata.fetch_metadata(invalid)
    assert not provider["calls"]


@pytest.mark.parametrize("status",[301,403,404,429,500])
def test_unavailable_metadata_no_redirect_no_retry(provider,status,caplog):
    provider["status"]=status
    assert metadata.fetch_metadata(VID) is None
    assert len(provider["calls"])==1
    assert "private" not in caplog.text


@pytest.mark.parametrize("change",[{"title":" "},{"title":None},{"title":123},{"title":"x"*1001},{"type":"photo"},{"provider_name":"attacker"}])
def test_invalid_response_never_invents_title(provider,change):
    provider["body"]=oembed(**change)
    assert metadata.fetch_metadata(VID) is None


def test_timeout_is_optional_safe_and_not_retried(provider,caplog):
    provider["timeout"]=True
    assert metadata.fetch_metadata(VID) is None
    assert len(provider["calls"])==1 and "private signed" not in caplog.text


def test_invalid_thumbnail_is_ignored(provider):
    provider["body"]=oembed(thumbnail_url="https://evil.example/thumbnail.jpg")
    assert metadata.fetch_metadata(VID).title==TITLE
    assert metadata.fetch_metadata(VID).thumbnail_url is None


@pytest.fixture
def metadata_store(monkeypatch,saved_videos):
    patches=[]
    def repair(video,title,thumbnail=None):
        current=saved_videos[video.video_id]
        updates={}
        if metadata.missing(current.title):updates["title"]=title
        if metadata.missing(current.thumbnail_url) and thumbnail:updates["thumbnail_url"]=thumbnail
        saved_videos[video.video_id]=current.model_copy(update=updates)
        patches.append(updates)
        return saved_videos[video.video_id]
    monkeypatch.setattr(repo,"repair_missing_metadata",Mock(side_effect=repair))
    return patches


def test_new_video_title_persisted_and_returned(monkeypatch,saved_videos,caption_api,metadata_store):
    fetch=Mock(return_value=metadata.VideoMetadata(TITLE,f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"))
    monkeypatch.setattr(metadata,"fetch_metadata",fetch);monkeypatch.setenv("TRANSCRIPT_SOURCE","auto")
    with TestClient(create_app()) as client:
        response=client.post("/api/videos/process",json={"url":URL})
    assert response.status_code==200 and response.json()["video"]["title"]==TITLE
    assert saved_videos[VID].title==TITLE and response.json()["transcript"]
    assert repo.upsert_video.call_args.args[0].title==TITLE
    fetch.assert_called_once_with(VID)


@pytest.mark.parametrize("old",[None,""," \t "])
def test_cached_missing_title_repaired_without_caption_fetch(monkeypatch,saved_videos,caption_api,make_record,metadata_store,old):
    saved_videos[VID]=make_record(title=old,thumbnail_url="https://example.com/existing.jpg",duration_seconds=123)
    original=saved_videos[VID].model_copy(deep=True)
    monkeypatch.setattr(metadata,"fetch_metadata",Mock(return_value=metadata.VideoMetadata(TITLE)))
    monkeypatch.setenv("TRANSCRIPT_SOURCE","auto")
    with TestClient(create_app()) as client:
        response=client.post("/api/videos/process",json={"url":URL})
    assert response.status_code==200 and response.json()["video"]["title"]==TITLE
    assert saved_videos[VID].transcript==original.transcript
    assert saved_videos[VID].thumbnail_url==original.thumbnail_url and saved_videos[VID].duration_seconds==123
    caption_api.list.assert_not_called();repo.upsert_video.assert_not_called()
    assert metadata_store==[{"title":TITLE}]


def test_existing_title_skips_metadata(monkeypatch,saved_videos,make_record,caption_api):
    saved_videos[VID]=make_record(title="Already real")
    fetch=Mock();monkeypatch.setattr(metadata,"fetch_metadata",fetch)
    response=video_service.process_video(URL)
    assert response.video.title=="Already real"
    fetch.assert_not_called();caption_api.list.assert_not_called()


def test_metadata_failure_preserves_success(monkeypatch,saved_videos,make_record,caption_api):
    saved_videos[VID]=make_record()
    monkeypatch.setattr(metadata,"fetch_metadata",lambda _:None)
    response=video_service.process_video(URL)
    assert response.mode=="real" and response.video.title is None and response.transcript
    caption_api.list.assert_not_called();repo.upsert_video.assert_not_called()


def test_failed_title_write_does_not_claim_success(monkeypatch,make_record):
    original=make_record()
    monkeypatch.setattr(metadata,"fetch_metadata",lambda _:metadata.VideoMetadata(TITLE))
    monkeypatch.setattr(repo,"repair_missing_metadata",Mock(side_effect=RuntimeError("private key")))
    assert metadata_enrichment.enrich_cached_video(original) is original


def test_production_metadata_is_distinct_from_captions(monkeypatch,saved_videos,make_record,caption_api,metadata_store):
    saved_videos[VID]=make_record()
    monkeypatch.setenv("APP_ENV","production");monkeypatch.setenv("TRANSCRIPT_SOURCE","auto")
    monkeypatch.setattr(metadata,"fetch_metadata",Mock(return_value=metadata.VideoMetadata(TITLE)))
    indexed=Mock();monkeypatch.setattr(video_service,"ensure_indexed",indexed)
    assert video_service.process_video(URL).video.title==TITLE
    indexed.assert_not_called();caption_api.list.assert_not_called()


def test_metadata_change_keeps_existing_vector_fingerprint(make_record):
    settings=RagSettings(openai_key="",pinecone_key="")
    video=make_record()
    assert build_plan(video,settings).fingerprint==build_plan(video.model_copy(update={"title":TITLE,"thumbnail_url":"https://example.com/another.jpg"}),settings).fingerprint


@pytest.fixture
def sdk_patch(monkeypatch,make_record):
    from app.db import supabase_client
    monkeypatch.setenv("SUPABASE_URL","https://unit.supabase.co");monkeypatch.setenv("SUPABASE_SECRET_KEY","sb_secret_unit-only")
    original=httpx.Client
    state={"row":make_record(title=" ",thumbnail_url=None).model_dump(mode="json"),"calls":[]}
    def handle(request):
        state["calls"].append(request)
        if request.method=="PATCH":
            update=json.loads(request.content)
            assert set(update)<={"title","thumbnail_url"} and len(update)==1
            for field,value in update.items():
                expected=request.url.params[field]
                if expected=="is.null" and state["row"][field] is None or expected=="eq."+str(state["row"][field]):
                    state["row"][field]=value
            return httpx.Response(200,json=[state["row"]])
        assert request.method=="GET"
        return httpx.Response(200,json=[state["row"]])
    monkeypatch.setattr(supabase_client.httpx,"Client",lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle)))
    return state


def test_real_sdk_conditional_patch_preserves_transcript_and_row(sdk_patch,make_record):
    before=sdk_patch["row"]["transcript"]
    result=repo.repair_missing_metadata(make_record(title=" ",thumbnail_url=None),TITLE,f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg")
    assert result.title==TITLE and sdk_patch["row"]["transcript"]==before
    assert [r.method for r in sdk_patch["calls"]]==["PATCH","PATCH","GET"]
    assert sdk_patch["calls"][0].url.params["title"]=="eq. "
    assert sdk_patch["calls"][1].url.params["thumbnail_url"]=="is.null"


def test_concurrent_nonempty_title_not_overwritten(sdk_patch,make_record):
    stale=make_record(title=" ")
    sdk_patch["row"]["title"]="Concurrent correct title"
    result=repo.repair_missing_metadata(stale,TITLE)
    assert result.title=="Concurrent correct title"


def test_backfill_dry_run_no_fetch_or_write(monkeypatch,make_record,capsys):
    monkeypatch.setattr(cli,"load_local_environment",lambda:None)
    monkeypatch.setattr(repo,"iter_video_metadata",lambda **kwargs:iter([{"video_id":VID,"title":None}]))
    fetch=Mock();write=Mock();monkeypatch.setattr(metadata,"fetch_metadata",fetch);monkeypatch.setattr(repo,"repair_missing_metadata",write)
    assert cli.main(["--dry-run","--limit","1"])==0
    fetch.assert_not_called();write.assert_not_called()
    assert "would fetch" in capsys.readouterr().out


def test_backfill_apply_updates_missing_and_skips_valid(monkeypatch,saved_videos,make_record,metadata_store,capsys):
    saved_videos[VID]=make_record()
    monkeypatch.setattr(cli,"load_local_environment",lambda:None)
    monkeypatch.setattr(repo,"iter_video_metadata",lambda **kwargs:iter([{"video_id":VID,"title":None},{"video_id":"abcdefghijk","title":"Already valid"}]))
    monkeypatch.setattr(metadata,"fetch_metadata",Mock(return_value=metadata.VideoMetadata(TITLE)))
    assert cli.main(["--apply","--limit","2"])==0
    assert saved_videos[VID].title==TITLE and len(metadata_store)==1
    assert "Updated: 1" in capsys.readouterr().out
