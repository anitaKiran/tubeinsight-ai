"""Explicit score-only dataset/experiment upload using the installed SDK."""
from datetime import datetime, timezone
import os
import re
from langsmith import Client
from urllib3 import Retry
from app.agent import observability  # Register safe SDK diagnostic filters.


def upload_report(report, *, client=None, experiment_name="tubeinsight-day4"):
    if report["mode"] != "live":
        raise ValueError("Only explicit live workflows may upload evaluation experiments.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", experiment_name):
        raise ValueError("Use a short public experiment label without private text.")
    rows = {r["id"]: r for r in report["results"] if r["status"] in {"passed", "failed"}}
    if not rows:
        raise ValueError("No measured results are available to upload.")
    if client is None:
        key = os.getenv("LANGSMITH_API_KEY", "").strip()
        if not key:
            raise ValueError("Configure LANGSMITH_API_KEY before uploading.")
        client = Client(api_key=key, timeout_ms=5000, retry_config=Retry(total=0),
            hide_inputs=True, hide_outputs=True, omit_traced_runtime_info=True)
    name = f"{experiment_name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    dataset = client.create_dataset(dataset_name=name, description="Score-only tubeInsight-ai evaluation; no prompts, transcripts, histories, or audio.",
        metadata={"revision": report["revision"], "backend_version": report["backend_version"]})
    client.create_examples(dataset_id=dataset.id, examples=[{"inputs": {"case_id": key}, "outputs": {"expected": 1}} for key in rows])
    def replay(inputs):
        row = rows[inputs["case_id"]]
        return {"pass": int(row["status"] == "passed"), "duration_seconds": row["duration_seconds"],
            "scores": [{k: int(v) for k,v in t["checks"].items() if isinstance(v, bool)} for t in row.get("turns", [])],
            "tool_selection": [t["tools"] for t in row.get("turns", [])],
            "judge": [t["judge"] for t in row.get("turns", []) if t.get("judge")]}
    def score(outputs, reference_outputs):
        results = [{"key": "deterministic_pass", "score": outputs["pass"]},
            {"key": "measured_duration_seconds", "score": outputs["duration_seconds"]}]
        keys = {key for turn in outputs["scores"] for key in turn}
        for key in sorted(keys):
            values = [turn[key] for turn in outputs["scores"] if key in turn]
            results.append({"key": key, "score": sum(values)/len(values)})
        for key in ("correctness", "evidence_support"):
            values = [turn[key] for turn in outputs["judge"]]
            if values:
                results.append({"key": "judge_"+key, "score": sum(values)/len(values)})
        return {"results": results}
    # Replays already measured sanitized results; never calls the agent twice.
    experiment = client.evaluate(replay, data=dataset.id, evaluators=[score], experiment_prefix=name,
        max_concurrency=0, num_repetitions=1, upload_results=True, disable_evaluator_tracing=True,
        metadata={"revision": report["revision"], "models": report["models"], "source": "sanitized-measured-replay"})
    list(experiment)
    client.flush(timeout=2)
    return name
