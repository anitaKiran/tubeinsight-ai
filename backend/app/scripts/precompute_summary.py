"""Explicit local summary precomputation; never fetch captions or index videos."""
import argparse
from pathlib import Path
from dataclasses import replace

from dotenv import load_dotenv
from app.agent.settings import AgentSettings, Budget
from app.agent.evidence import Evidence
from app.agent.model import open_agent_model
from app.agent.summarization import summarize
from app.agent.observability import observe_request
from app.rag.settings import RagSettings
from app.repositories.video_repository import get_video
from app.runtime import require_local_extraction
from app.schemas.error import ApiException
from app.services.youtube_url import extract_video_id


def main(argv=None):
    parser = argparse.ArgumentParser(description="Precompute one saved video's summary. Model calls may incur usage.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--detail", choices=["brief", "detailed"], default="brief")
    parser.add_argument("--max-batches", type=int, default=12)
    args = parser.parse_args(argv)
    if not 1 <= args.max_batches <= 50:
        parser.error("--max-batches must be 1 to 50")
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    try:
        require_local_extraction()
        video_id = extract_video_id("https://youtu.be/" + args.video_id)
        video = get_video(video_id)
        if video is None:
            raise ApiException(404, "VIDEO_NOT_FOUND", "This video has not been saved.")
        settings = replace(AgentSettings.from_env(), summary_max_batches=args.max_batches,
            max_model_calls=args.max_batches + 3, request_seconds=600)
        budget = Budget(settings)
        with observe_request(video_id), open_agent_model(RagSettings.from_env(), budget) as model:
            result = summarize(video, Evidence(video_id), settings, RagSettings.from_env(), budget, model, detail=args.detail)
        if result.get("empty") or not result.get("results"):
            raise ApiException(404, "TRANSCRIPT_NOT_AVAILABLE", "No grounded summary could be generated from the transcript.")
        print(f"{video_id}: summary {'cached' if result.get('cached') else 'saved'}; sources={len(result.get('results', []))}")
        return 0
    except ApiException as error:
        print(f"{error.code}: {error.message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
