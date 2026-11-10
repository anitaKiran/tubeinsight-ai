import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.agent.observability import capture_operations, operation
from app.evaluation.dataset import load_dataset, Dataset, transcript_hash
from app.evaluation.scoring import abstention, score_turn, source_checks, word_error_rate, latency_summary
from app.evaluation.run import authorize, evaluate, main, CallLimit
from app.evaluation.report import write_reports
from app.rag.answering import INSUFFICIENT_EVIDENCE


@pytest.fixture
def dataset():
    return load_dataset("offline")


def test_offline_all_cases_actual_services_and_no_network(dataset):
    results, used = evaluate(dataset)
    assert used == 0  # Paid calls only; scripted LLM spans are still measured.
    assert all(r["status"] == "passed" for r in results), [(r["id"],r.get("error_code"),r.get("turns")) for r in results if r["status"] != "passed"]
    memory = next(r for r in results if r["category"] == "memory")
    assert memory["memory"]["fresh_app_reuse"] and memory["memory"]["cross_video_rejected"]
    assert memory["memory"]["ordered_history"] and memory["memory"]["memory_window"]
    assert memory["turns"][1]["checks"]["reference_phrase_coverage"]
    assert all(r["audio"]["wer"] is None for r in results if "audio" in r)
    assert all(t["semantic_correctness"] is None for r in results for t in r["turns"])


def test_unreviewed_real_references_untested(monkeypatch):
    monkeypatch.setenv("EVALUATION_ENABLE_LIVE", "true")
    dataset = load_dataset("curated")
    results, used = evaluate(dataset, mode="live", max_examples=3, enable_live=True)
    assert used == 0 and all(r["status"] == "untested" for r in results)


@pytest.mark.parametrize("change", ["duplicate", "unknown_tool", "range", "facts", "missing_video"])
def test_reference_validation(dataset, change):
    raw = dataset.model_dump()
    if change == "duplicate": raw["cases"].append(raw["cases"][0])
    if change == "unknown_tool": raw["cases"][0]["turns"][0]["acceptable_tools"] = [["browse_web"]]
    if change == "range": raw["cases"][0]["turns"][0]["expected_range"] = [20,10]
    if change == "facts": raw["cases"][0]["turns"][0]["expected_facts"] = []
    if change == "missing_video": raw["cases"][0]["video_id"] = "missing0001"
    with pytest.raises(ValueError): Dataset.model_validate(raw)


def test_reviewed_real_requires_hash():
    raw = load_dataset("curated").model_dump()
    raw["cases"][0].update(reviewed=True, review_note="Checked original captions")
    raw["cases"][0]["turns"][0]["expected_facts"] = ["Known reference fact"]
    with pytest.raises(ValueError): Dataset.model_validate(raw)


def test_canonical_abstention_and_keywords_not_grounding():
    assert abstention(INSUFFICIENT_EVIDENCE) is True
    assert abstention("I cannot answer, but his address is 123 Main Street.") is None
    assert abstention("The sky is purple.") is None


def test_sources_timestamps_and_cross_video(dataset):
    video, turn = dataset.videos[0], dataset.cases[0].turns[0]
    response = {"video_id":video.video_id,"answer":"six hours", "sources":[video.transcript[0].model_dump()]}
    assert all(source_checks(video,response,turn).values())
    response["sources"][0]["start_seconds"] = 2
    assert not source_checks(video,response,turn)["timestamp_validity"]
    response["sources"][0] = video.transcript[1].model_dump()
    response["sources"][0]["text"] = "Made-up quotation"
    assert not source_checks(video,response,turn)["source_provenance"]
    response["sources"][0] = video.transcript[0].model_dump()
    response["sources"][0]["video_id"] = dataset.videos[1].video_id
    assert not source_checks(video,response,turn)["video_isolation"]
    assert not source_checks(None,response,turn)["video_exists"]


def test_range_and_real_tool_events_required(dataset):
    video, turn = dataset.videos[0], dataset.cases[4].turns[0]
    response = {"video_id":video.video_id,"answer":"Compost adds nutrients", "sources":[video.transcript[0].model_dump()]}
    scored = score_turn(video,response,turn,[])
    assert scored["checks"]["range_overlap"] is False and scored["checks"]["tool_selection"] is False
    events = [{"name":"tool.get_transcript_segment","success":True}]*4
    scored = score_turn(video,response,turn,events)
    assert scored["checks"]["tool_call_limit"] is False
    assert scored["checks"]["tool_selection"] is True


def test_multiple_acceptable_tool_sets(dataset):
    turn = dataset.cases[-7].turns[0]  # Combined-tools case before audio cases.
    turn = turn.model_copy(update={"acceptable_tools":[["search_transcript"],["get_transcript_segment","search_transcript"]]})
    video=dataset.videos[0]
    response={"video_id":video.video_id,"answer":"Basil", "sources":[video.transcript[1].model_dump()]}
    events=[{"name":"tool.search_transcript","success":False}]
    scored=score_turn(video,response,turn,events)
    assert scored["checks"]["tool_selection"] and not scored["checks"]["tool_execution"]
    assert scored["tool_failures"] == 1


def test_monotonic_events_failure_and_context_isolation():
    with capture_operations() as events:
        with operation("tool.search_transcript","tool"):
            pass
        with pytest.raises(RuntimeError):
            with operation("model","llm"):
                raise RuntimeError("private error")
    assert len(events) == 2 and all(e["duration_seconds"] >= 0 for e in events)
    assert not events[1]["success"] and "private" not in str(events)
    with capture_operations() as fresh:
        pass
    assert not fresh


def test_latency_and_wer():
    assert latency_summary([])["p95"] is None
    assert latency_summary([1,2,3,4])["p50"] == 2.5
    assert latency_summary([1])["n"] == 1
    assert word_error_rate("Hello, world!","hello world") == 0
    assert word_error_rate("one two three","one three") == pytest.approx(1/3)


@pytest.mark.parametrize("flag,env", [(False,"false"),(True,"false"),(False,"true")])
def test_live_two_independent_guards(monkeypatch, flag, env):
    monkeypatch.setenv("EVALUATION_ENABLE_LIVE", env)
    with pytest.raises(ValueError): authorize("live", live_flag=flag)


def test_live_limits_and_upload_disabled_default(monkeypatch):
    authorize("offline")
    for option in ["upload","judge","live_flag"]:
        with pytest.raises(ValueError): authorize("offline", **{option:True})
    monkeypatch.setenv("EVALUATION_ENABLE_LIVE","true")
    with pytest.raises(ValueError): authorize("live",live_flag=True,max_examples=6)
    with pytest.raises(ValueError): authorize("live",live_flag=True,max_calls=31)
    guard=CallLimit(1); guard.take()
    with pytest.raises(Exception): guard.take()
    assert guard.used == 1


def test_json_markdown_csv_reports_are_content_free(dataset,tmp_path):
    results,_=evaluate(dataset,max_examples=1)
    report,paths=write_reports(dataset,"offline",results,tmp_path,{"chat":"scripted"})
    assert all(p.is_file() for p in paths)
    assert json.loads(paths[0].read_text(encoding="utf-8"))["case_count"] == 1
    assert report["summary"]["semantic_cases_untested"] == 1
    content=paths[0].read_text(encoding="utf-8")
    assert "Tomatoes need" not in content and "six hours" not in content
    assert "conversation_id" not in content


def test_default_cli_offline_generates_report(tmp_path,monkeypatch):
    upload=Mock()
    monkeypatch.setattr("app.evaluation.langsmith_export.upload_report",upload)
    assert main(["--max-examples","1","--output-dir",str(tmp_path)]) == 0
    upload.assert_not_called()
    assert list(tmp_path.glob("*.json"))


def test_langsmith_current_sdk_signature_and_redacted_payload(dataset, tmp_path):
    from langsmith import Client
    from app.evaluation.langsmith_export import upload_report
    import inspect
    assert "disable_evaluator_tracing" in inspect.signature(Client.evaluate).parameters
    results,_=evaluate(dataset,max_examples=1)
    report,_=write_reports(dataset,"live",results,tmp_path,{"chat":"test"})
    client=Mock()
    client.create_dataset.return_value=SimpleNamespace(id="dataset-id")
    client.evaluate.return_value=[]
    upload_report(report,client=client)
    examples=client.create_examples.call_args.kwargs["examples"]
    assert examples == [{"inputs":{"case_id":"tomato-fact"},"outputs":{"expected":1}}]
    kwargs=client.evaluate.call_args.kwargs
    assert kwargs["max_concurrency"] == 0 and kwargs["disable_evaluator_tracing"]
    target=client.evaluate.call_args.args[0]
    assert "sources" not in str(target({"case_id":"tomato-fact"}))


def test_transcript_hash_detects_changed_reference(dataset):
    video=dataset.videos[0]
    before=transcript_hash(video)
    changed=video.model_copy(deep=True)
    changed.transcript[0].text="Changed transcript"
    assert transcript_hash(changed) != before


def test_offline_blocks_external_connections(dataset):
    from app.evaluation.offline import offline_services
    import socket
    import httpx
    with offline_services(dataset):
        with pytest.raises(AssertionError):
            socket.create_connection(("example.com",443))
        with pytest.raises(AssertionError):
            httpx.get("https://example.com")


def test_global_live_budget_limits_model_calls_across_cases(dataset, monkeypatch):
    from app.evaluation.offline import offline_services
    monkeypatch.setenv("EVALUATION_ENABLE_LIVE","true")
    raw=dataset.model_dump()
    raw.update(level="real",videos=[],cases=raw["cases"][:2])
    for case in raw["cases"]:
        case["transcript_sha256"]=transcript_hash(dataset.videos[0])
    real=Dataset.model_validate(raw)
    with offline_services(dataset) as memory:
        results,used=evaluate(real,mode="live",max_examples=2,max_model_calls=1,enable_live=True)
        assert used == 1
        assert results[0]["error_code"] == "EVALUATION_CALL_LIMIT"
        assert results[1]["status"] == "skipped"
        assert not memory.messages  # No partial failed exchange.


def test_llm_judge_real_sdk_schema_and_scores(monkeypatch, dataset):
    import httpx2
    from openai import OpenAI
    from app.evaluation import judge as module
    captured=[]
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx2.Response(200,json={"id":"judge-test","object":"chat.completion","created":0,"model":"gpt-6-luna",
            "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":'{"correctness":1,"evidence_support":1}'}}]})
    monkeypatch.setattr(module,"OpenAI",lambda **kwargs:OpenAI(**kwargs,http_client=httpx2.Client(transport=httpx2.MockTransport(respond))))
    response={"answer":"six hours", "sources":[dataset.videos[0].transcript[0].model_dump()]}
    scores=module.judge(dataset.cases[0].turns[0],response,"unit-judge-key","gpt-6-luna")
    assert scores == {"correctness":1,"evidence_support":1}
    assert captured[0]["response_format"]["type"] == "json_schema"
    assert "untrusted" in captured[0]["messages"][0]["content"]


def test_langsmith_feedback_normalizes_with_installed_sdk(dataset, tmp_path):
    from uuid import uuid4
    from datetime import datetime, timezone
    from langsmith.evaluation import run_evaluator
    from langsmith.schemas import Run, Example
    from app.evaluation.langsmith_export import upload_report
    results,_=evaluate(dataset,max_examples=1)
    report,_=write_reports(dataset,"live",results,tmp_path,{"chat":"test"})
    client=Mock();client.create_dataset.return_value=SimpleNamespace(id=uuid4());client.evaluate.return_value=[]
    upload_report(report,client=client)
    target=client.evaluate.call_args.args[0]
    evaluator=client.evaluate.call_args.kwargs["evaluators"][0]
    run=Run(id=uuid4(), name="sanitized",run_type="chain",start_time=datetime.now(timezone.utc),inputs={},outputs=target({"case_id":"tomato-fact"}))
    example=Example(id=uuid4(),dataset_id=uuid4(),inputs={},outputs={"expected":1},created_at=datetime.now(timezone.utc))
    scored=run_evaluator(evaluator).evaluate_run(run,example)
    assert {r.key for r in scored["results"]} >= {"deterministic_pass","measured_duration_seconds","source_provenance"}
