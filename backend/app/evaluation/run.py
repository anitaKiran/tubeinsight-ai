"""python -m app.evaluation.run --mode offline (default, no network or uploads)."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from app.agent.observability import capture_operations
from app.agent.settings import Budget
from app.evaluation.dataset import load_dataset, transcript_hash
from app.evaluation.report import write_reports
from app.evaluation.scoring import score_turn, word_error_rate
from app.schemas.error import ApiException

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = BACKEND / "evaluation" / "fixtures"


class CallLimit:
    def __init__(self, maximum):
        self.maximum, self.used = maximum, 0

    def take(self):
        if self.used >= self.maximum:
            raise ApiException(422, "EVALUATION_CALL_LIMIT", "Evaluation reached its model-call limit.")
        self.used += 1


@contextmanager
def live_services(limit):
    from app.services import chat_service
    class EvaluationBudget(Budget):
        def model(self):
            super().model()
            limit.take()
    with patch.object(chat_service, "Budget", EvaluationBudget):
        yield None


def audio_case(case, mode, limit):
    from fastapi.testclient import TestClient
    from app.main import create_app
    path = (FIXTURES/case.audio_fixture).resolve()
    if not path.is_relative_to(FIXTURES.resolve()) or not path.is_file():
        return {"status": "skipped", "reason": "Audio fixture unavailable; no accuracy measured.", "audio": {"wer": None}}
    if mode == "live":
        limit.take()  # Conservative reservation, even if validation prevents a call.
    with TestClient(create_app()) as client, path.open("rb") as handle:
        response = client.post("/api/audio/transcribe", files={"file": (path.name, handle, "application/octet-stream")})
    if case.expected_error:
        passed = response.status_code >= 400 and response.json().get("error", {}).get("code") == case.expected_error
        return {"status": "passed" if passed else "failed", "audio": {"expected_error_observed": passed, "wer": None}}
    if response.status_code != 200:
        return {"status": "failed", "error_code": response.json().get("error", {}).get("code", "AUDIO_FAILURE"), "audio": {"wer": None}}
    wer = word_error_rate(case.reference_text, response.json()["text"]) if mode == "live" else None
    return {"status": "passed", "audio": {"response_schema": set(response.json()) == {"text", "language", "model"}, "wer": wer,
        "accuracy_status": "measured, human acceptance review still required" if mode == "live" else "untested; mocked transcription"}}


def evaluate(dataset, *, mode="offline", max_examples=100, max_model_calls=12, use_judge=False, enable_live=False):
    authorize(mode, live_flag=enable_live, judge=use_judge, max_examples=max_examples, max_calls=max_model_calls)
    if (mode == "offline") != (dataset.level == "synthetic"):
        raise ValueError("Evaluation mode and dataset level must match.")
    from app.repositories import video_repository
    from app.services import chat_service
    from app.evaluation.offline import offline_services
    limit = CallLimit(max_model_calls)
    context = offline_services(dataset) if mode == "offline" else live_services(limit)
    results = []
    with context as memory:
        for case in dataset.cases[:max_examples]:
            started = time.monotonic()
            row = {"id": case.id, "category": case.category, "status": "untested", "turns": []}
            with capture_operations() as events:
                try:
                    if not case.reviewed:
                        row["reason"] = "Reference requires manual transcript/audio review."
                    elif mode == "live" and limit.used >= limit.maximum:
                        row.update(status="skipped", reason="Global model-call limit reached.")
                    elif case.category == "audio":
                        row.update(audio_case(case, mode, limit))
                    else:
                        video = video_repository.get_video(case.video_id)
                        if video is None:
                            row.update(status="failed", error_code="VIDEO_NOT_FOUND")
                        elif mode == "live" and transcript_hash(video) != case.transcript_sha256:
                            row.update(status="untested", reason="Cached transcript changed; references require re-review.")
                        else:
                            conversation = None
                            for turn in case.turns:
                                offset = len(events)
                                # Actual existing backend service and actual native tools.
                                if mode == "offline" and case.category == "memory" and conversation is not None:
                                    from fastapi.testclient import TestClient
                                    from app.main import create_app
                                    from app.schemas.chat import ChatResponse
                                    with TestClient(create_app()) as client:
                                        reply = client.post("/api/chat/ask", json={"video_id": case.video_id, "question": turn.question, "conversation_id": str(conversation)})
                                    if reply.status_code != 200:
                                        raise ApiException(reply.status_code, reply.json()["error"]["code"], "Evaluation follow-up failed.")
                                    response = ChatResponse.model_validate(reply.json())
                                else:
                                    response = chat_service.ask_question(case.video_id, turn.question, conversation)
                                turn_events = events[offset:]
                                from app.rag.settings import RagSettings
                                scored = score_turn(video, response.model_dump(mode="json"), turn, turn_events,
                                    max_tools=int(os.getenv("AGENT_MAX_TOOL_CALLS", "3")), settings=RagSettings.from_env())
                                scored["answerable"] = turn.answerable
                                scored["checks"]["conversation_reuse"] = conversation is None or response.conversation_id == conversation
                                conversation = response.conversation_id
                                if use_judge and all(scored["checks"][k] for k in ("source_provenance", "video_isolation", "timestamp_validity")):
                                    from app.evaluation.judge import judge
                                    limit.take()
                                    scored["judge"] = judge(turn, response.model_dump(mode="json"), os.environ["OPENAI_API_KEY"], os.environ["OPENAI_CHAT_MODEL"])
                                row["turns"].append(scored)
                            row["status"] = "failed" if any(value is False for turn in row["turns"] for key,value in turn["checks"].items() if key != "reference_phrase_coverage") or any(t.get("judge") and not all(t["judge"].values()) for t in row["turns"]) else "passed"
                            if case.category == "memory" and memory is not None:
                                history = memory.messages[conversation]
                                row["memory"] = {"ordered_history": [m["sequence_number"] for m in history] == list(range(len(history))),
                                    "all_turns_persisted": len(history) == len(case.turns)*2,
                                    "fresh_app_reuse": True, "live_restart": "untested; fake repository"}
                                fresh = memory.claim(None, case.video_id, 75)
                                row["memory"]["independent_session_empty"] = not memory.history(fresh, 12, 12000)
                                memory.release(fresh)
                                from types import SimpleNamespace
                                bounded = memory.history(SimpleNamespace(session_id=conversation), 2, 12000)
                                row["memory"]["memory_window"] = len(bounded) == 2 and bounded[0]["role"] == "user"
                                other = next((v.video_id for v in dataset.videos if v.video_id != case.video_id), None)
                                if other:
                                    try:
                                        chat_service.ask_question(other, "Explain the second one.", conversation)
                                    except ApiException as error:
                                        row["memory"]["cross_video_rejected"] = error.code == "CONVERSATION_NOT_FOUND"
                                    else:
                                        row["memory"]["cross_video_rejected"] = False
                                if any(value is False for value in row["memory"].values()):
                                    row["status"] = "failed"
                except ApiException as error:
                    row.update(status="failed", error_code=error.code)
                except Exception:
                    row.update(status="failed", error_code="EVALUATION_EXECUTION_FAILED")
            row["events"] = list(events)  # Content-free names, durations and safe codes only.
            row["duration_seconds"] = max(0.0, time.monotonic()-started)
            results.append(row)
    return results, limit.used


def authorize(mode, *, live_flag=False, upload=False, judge=False, max_examples=3, max_calls=12):
    if mode == "offline":
        if live_flag or upload or judge:
            raise ValueError("Offline mode forbids live calls, judge calls and LangSmith uploads.")
    elif not live_flag or os.getenv("EVALUATION_ENABLE_LIVE", "false").lower() != "true":
        raise ValueError("Live evaluation requires EVALUATION_ENABLE_LIVE=true and --enable-live.")
    if mode == "live" and (not 1 <= max_examples <= 5 or not 1 <= max_calls <= 30):
        raise ValueError("Live limits: 1–5 examples and 1–30 model calls. Bulk runs require a separate reviewed workflow.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--dataset")
    parser.add_argument("--max-examples", type=int)
    parser.add_argument("--max-model-calls", type=int, default=12)
    parser.add_argument("--enable-live", action="store_true")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--upload-langsmith", action="store_true")
    parser.add_argument("--experiment-name", default="tubeinsight-day4")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    if args.mode == "live":
        from dotenv import load_dotenv
        load_dotenv(BACKEND/".env")
    maximum = args.max_examples if args.max_examples is not None else (3 if args.mode == "live" else 100)
    if maximum < 1:
        parser.error("--max-examples must be positive.")
    try:
        authorize(args.mode, live_flag=args.enable_live, upload=args.upload_langsmith, judge=args.judge,
            max_examples=maximum, max_calls=args.max_model_calls)
        dataset = load_dataset(args.dataset or ("offline" if args.mode == "offline" else "curated"))
        if args.mode == "offline" and dataset.level != "synthetic" or args.mode == "live" and dataset.level != "real":
            raise ValueError("Offline requires synthetic references; live requires reviewed real-video references.")
        if args.mode == "live":
            print(f"WARNING: explicit live evaluation may incur AI charges and persist test conversations: at most {maximum} cases and {args.max_model_calls} model-call reservations. No indexing or extraction is performed.", file=sys.stderr)
        results, used = evaluate(dataset, mode=args.mode, max_examples=maximum, max_model_calls=args.max_model_calls, use_judge=args.judge, enable_live=args.enable_live)
        models = {"chat": os.getenv("OPENAI_CHAT_MODEL", "gpt-6-luna"), "embeddings": "llama-text-embed-v2 / 1024",
            "transcription": os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"), "providers": "scripted" if args.mode == "offline" else "live"}
        report, paths = write_reports(dataset, args.mode, results, args.output_dir or os.getenv("EVALUATION_OUTPUT_DIR", "reports/evaluation"), models, model_calls=used)
        for path in paths:
            print(path.resolve())
        print(report["summary"]["counts"])
        if args.upload_langsmith:
            from app.evaluation.langsmith_export import upload_report
            upload_report(report, experiment_name=args.experiment_name)
    except (ValueError, OSError):
        parser.error("Invalid evaluation configuration or dataset. Review reference validation, live opt-in, limits and file paths. No secrets are printed.")
    except Exception:
        print("Evaluation/export failed. Check configuration and safe local report error codes.", file=sys.stderr)
        return 1
    return 1 if report["summary"]["counts"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
