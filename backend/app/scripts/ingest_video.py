"""python -m app.scripts.ingest_video URL [--force]"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas.error import ApiException
from app.services.ingestion_service import IngestionResult, ingest_video


def load_local_environment() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def print_result(result: IngestionResult) -> None:
    print(f"Video ID: {result.video.video_id}")
    print(f"Transcript segments: {len(result.video.transcript)}")
    print(f"Language: {result.video.language or 'unknown'}")
    print("Status: Cached in Supabase (extraction skipped)" if result.cached
          else "Status: Saved to Supabase successfully")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tubeInsight-ai local transcript ingestion")
    parser.add_argument("url", help="YouTube watch, short, or Shorts URL")
    parser.add_argument("--force", action="store_true", help="Refresh an existing saved transcript")
    args = parser.parse_args(argv)
    load_local_environment()
    print("tubeInsight-ai Transcript Ingestion\n")
    try:
        print_result(ingest_video(args.url, force=args.force))
        return 0
    except ApiException as exc:
        print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
    except ValidationError:
        print("Error [VALIDATION_ERROR]: Extracted captions could not be saved.", file=sys.stderr)
    except Exception:
        print("Error [INTERNAL_SERVER_ERROR]: Ingestion failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
