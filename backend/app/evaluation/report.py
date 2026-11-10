import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from app.evaluation.scoring import latency_summary


def aggregate(results):
    counts = {state: sum(r["status"] == state for r in results) for state in ("passed", "failed", "skipped", "untested")}
    turns = [t for r in results for t in r.get("turns", [])]
    def rate(key, selected=None):
        rows = turns if selected is None else selected
        vals = [t["checks"].get(key) for t in rows if t["checks"].get(key) is not None]
        return {"passed": sum(v is True for v in vals), "n": len(vals), "rate": sum(v is True for v in vals)/len(vals) if vals else None}
    unsupported = [t for t in turns if not t["answerable"]]
    events = [e for r in results for e in r.get("events", [])]
    tool_events = [e for e in events if e["name"].startswith("tool.")]
    audio = [r for r in results if r["category"] == "audio"]
    wers = [r["audio"]["wer"] for r in audio if r.get("audio", {}).get("wer") is not None]
    memory = [r for r in results if r["category"] == "memory"]
    timings = {name: latency_summary([e["duration_seconds"] for e in events if e["name"] == name]) for name in sorted({e["name"] for e in events})}
    unsupported_judged = [t["judge"] for t in unsupported if t.get("judge")]
    semantics = [t.get("judge") for t in turns if t.get("judge")]
    return {"counts": counts, "by_category": {c: {s: sum(r["category"] == c and r["status"] == s for r in results) for s in counts} for c in sorted({r["category"] for r in results})},
        "metrics": {key: rate(key) for key in ("source_provenance", "timestamp_validity", "range_overlap", "video_isolation", "tool_selection", "tool_execution", "tool_call_limit", "reference_phrase_coverage")},
        "unsupported": {"correct_abstention": rate("appropriate_abstention", unsupported),
            "non_abstaining_responses": sum(t["checks"]["appropriate_abstention"] is False for t in unsupported),
            "confirmed_false_answers": sum(j.get("correctness") == 0 for j in unsupported_judged),
            "false_answer_rate": sum(j["correctness"] == 0 for j in unsupported_judged)/len(unsupported_judged) if unsupported_judged else None, "judge_sample_size": len(unsupported_judged), "note": "Non-abstention is a failure for unsupported cases, but is not alone proof of a fabricated claim. Unjudged false-answer rate is unknown."},
        "unnecessary_tool_calls": sum(t["unnecessary_tool_calls"] for t in turns),
        "tool_execution_failures": sum(not e["success"] for e in tool_events),
        "tool_execution_failure_rate": sum(not e["success"] for e in tool_events)/len(tool_events) if tool_events else None,
        "execution_limit_rejections": sum(r.get("error_code") in {"AGENT_LIMIT_REACHED", "EVALUATION_CALL_LIMIT"} for r in results),
        "audio": {"cases": len(audio), "measured_wer_n": len(wers), "mean_wer": sum(wers)/len(wers) if wers else None,
            "untested_accuracy_cases": sum(r.get("audio", {}).get("accuracy_status", "").startswith("untested") for r in audio)},
        "memory": {"cases": len(memory), "passed_mechanical": sum(r["status"] == "passed" for r in memory),
            "follow_up_semantics": "Judge or human review required; offline reference phrase coverage is diagnostic only."},
        "evidence_support_score": sum(j["evidence_support"] for j in semantics)/len(semantics) if semantics else None,
        "answer_correctness_score": sum(j["correctness"] for j in semantics)/len(semantics) if semantics else None,
        "cross_video_citation_violations": sum(t["checks"]["video_isolation"] is False for t in turns),
        "tool_limit_violations": sum(t["checks"]["tool_call_limit"] is False for t in turns),
        "semantic_cases_judged": len(semantics), "semantic_cases_untested": len(turns)-len(semantics),
        "latency_seconds": latency_summary([r["duration_seconds"] for r in results if r["status"] in ("passed", "failed")]),
        "operation_latency_seconds": timings,
        "success_count": counts["passed"], "failure_count": counts["failed"]}


def write_reports(dataset, mode, results, output_dir, models, *, model_calls=0):
    now = datetime.now(timezone.utc)
    report = {"created_at": now.isoformat(), "backend_version": "0.6.0", "dataset": dataset.name, "revision": dataset.revision,
        "level": dataset.level, "mode": mode, "models": models, "model_calls": model_calls, "case_count": len(results),
        "measurement_scope": "Scripted provider regression; does not measure real model quality or provider latency." if mode == "offline" else "Limited live evaluation; semantic results require reviewed references and human or judge review.",
        "limitations": ["Mechanical checks cannot establish factual correctness or semantic evidence support.",
            "Unreviewed references are untested; skipped audio fixtures are not measured.", "Offline ASR WER is untested; mocked speech output is not a transcription accuracy measurement.",
            "Small-sample p95 is unstable. Timings include nested spans and must not be added together.",
            "Fresh app instances over a fake persistent store test restart logic; actual process restart and live DB durability need separate opt-in verification.",
            "Reports omit questions, answers, source text, audio and conversation IDs."],
        "summary": aggregate(results), "results": results}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = f"{dataset.name}-{mode}-{now.strftime('%Y%m%dT%H%M%S%fZ')}"
    json_path, md_path, csv_path = [output/f"{stem}.{ext}" for ext in ("json", "md", "csv")]
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = ["# tubeInsight-ai evaluation", "", f"Date: {report['created_at']}", f"Backend: 0.6.0 · Dataset: {dataset.name} / {dataset.revision} · Mode: {mode}",
        "", report["measurement_scope"], "", f"Cases: {len(results)} · " + " · ".join(f"{k}: {v}" for k,v in report["summary"]["counts"].items()),
        "", "A passed case means applicable deterministic checks passed. Semantic correctness and ASR accuracy remain untested unless explicitly judged/measured.",
        "", "| Case | Category | Status | Seconds |", "|---|---|---|---:|"]
    rows += [f"| {r['id']} | {r['category']} | {r['status']} | {r['duration_seconds']:.4f} |" for r in results]
    rows += ["", "## Metrics", "", "```json", json.dumps(report["summary"], indent=2), "```", "", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    md_path.write_text("\n".join(rows)+"\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "category", "status", "duration_seconds"])
        writer.writeheader()
        writer.writerows({k:r[k] for k in writer.fieldnames} for r in results)
    return report, [json_path, md_path, csv_path]
