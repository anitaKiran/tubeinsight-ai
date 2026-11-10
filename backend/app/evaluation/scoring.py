"""Mechanical checks are separate from human/optional judge semantic scores."""
import math
import re
from app.rag.answering import INSUFFICIENT_EVIDENCE
from app.rag.chunking import build_plan
from app.rag.settings import RagSettings


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def abstention(answer):
    # Exact server-owned abstention is strong evidence of the supported=false
    # path. Other wording needs review; keywords never prove groundedness.
    return True if answer.strip() == INSUFFICIENT_EVIDENCE else None


def source_checks(video, response, turn, settings=None):
    if video is None:
        return {"video_exists": False, "video_isolation": False, "source_provenance": False, "timestamp_validity": False, "range_overlap": False}
    settings = settings or RagSettings(openai_key="", pinecone_key="")
    segments = video.transcript
    candidates = [(s.text, s.start_seconds, s.end_seconds) for s in segments]
    candidates += [(d.page_content, d.metadata["start_seconds"], d.metadata["end_seconds"]) for d in build_plan(video, settings).documents]
    if turn.expected_range:
        left, right = turn.expected_range
        subset = [s for s in segments if s.end_seconds > left and s.start_seconds < right]
        if subset:
            candidates += [(d.page_content, d.metadata["start_seconds"], d.metadata["end_seconds"]) for d in build_plan(video.model_copy(update={"transcript": subset}), settings).documents]
    def close(a, b):
        return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) and math.isclose(a, b, rel_tol=0, abs_tol=1e-6)
    provenance, timestamps, overlaps = [], [], []
    for source in response.get("sources", []):
        text, start, end = source.get("text"), source.get("start_seconds"), source.get("end_seconds")
        # Only exact original segments, current chunks, or a contiguous original
        # excerpt with matching segment boundaries are accepted. Mere substring
        # occurrence elsewhere in a video cannot validate a timestamp.
        exact = any(text == t and close(start, a) and close(end, b) for t, a, b in candidates)
        if not exact:
            for i, first in enumerate(segments):
                if not close(start, first.start_seconds):
                    continue
                text_parts = []
                for last in segments[i:]:
                    text_parts.append(last.text)
                    if close(end, last.end_seconds) and text in ("\n".join(text_parts), " ".join(text_parts)):
                        exact = True
                        break
        provenance.append(exact)
        timestamps.append(exact and isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= start <= end)
        overlaps.append(turn.expected_range is None or (exact and end > turn.expected_range[0] and start < turn.expected_range[1]))
    required = turn.answerable
    present = bool(response.get("sources")) or not required
    isolation = response.get("video_id") == video.video_id and all(s.get("video_id", video.video_id) == video.video_id for s in response.get("sources", []))
    return {"video_exists": True, "video_isolation": isolation,
        "source_provenance": present and all(provenance), "timestamp_validity": present and all(timestamps),
        "range_overlap": present and all(overlaps)}


def score_turn(video, response, turn, events, *, max_tools=3, settings=None):
    checks = source_checks(video, response, turn, settings)
    tools = [e["name"].removeprefix("tool.") for e in events if e["name"].startswith("tool.")]
    expected = [set(seq) for seq in turn.acceptable_tools]
    actual = set(tools)
    checks.update(tool_selection=actual in expected, tool_call_limit=len(tools) <= max_tools,
        tool_execution=all(e["success"] for e in events if e["name"].startswith("tool.")))
    canonical = abstention(response.get("answer", ""))
    if turn.answerable:
        checks["appropriate_abstention"] = canonical is not True
    else:
        checks["appropriate_abstention"] = canonical is True and not response.get("sources")
    # Reference phrase coverage is a diagnostic, never a semantic verdict.
    facts = [normalize(f) in normalize(response.get("answer", "")) for f in turn.expected_facts]
    checks["reference_phrase_coverage"] = all(facts) if facts else None
    return {"checks": checks, "tools": tools,
        "unnecessary_tool_calls": min((len(tools) - len(actual) + len(actual - seq) for seq in expected), default=len(actual)),
        "tool_failures": sum(not e["success"] for e in events if e["name"].startswith("tool.")),
        "semantic_correctness": None, "evidence_support": None,
        "semantic_review": "Human review or explicit judge required; phrase matching does not establish correctness or support."}


def word_error_rate(reference, hypothesis):
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    if not ref:
        return None
    previous = list(range(len(hyp) + 1))
    for i, word in enumerate(ref, 1):
        current = [i]
        for j, other in enumerate(hyp, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (word != other)))
        previous = current
    return previous[-1] / len(ref)


def latency_summary(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    def percentile(p):
        index = (len(values) - 1) * p
        low, high = math.floor(index), math.ceil(index)
        return values[low] + (values[high] - values[low]) * (index - low)
    return {"n": len(values), "mean": sum(values)/len(values), "p50": percentile(.5), "p95": percentile(.95), "max": values[-1],
        "note": "p95 is not statistically stable for small samples (especially n < 100)."}
