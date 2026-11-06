"""Explicit, idempotent indexing of saved Supabase captions; never fetch YouTube."""

import argparse
from itertools import islice
from pathlib import Path
import sys

from dotenv import load_dotenv

from app.rag.indexing import ensure_indexed
from app.repositories import video_repository
from app.runtime import require_local_extraction
from app.schemas.error import ApiException
from app.services.youtube_url import extract_video_id


def main(argv=None):
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description="Index saved transcripts. OpenAI embeddings and Pinecone usage may incur costs.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--video-id", help="A saved YouTube video ID (or URL).")
    selection.add_argument("--all", action="store_true", help="Explicit bulk backfill of saved videos.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum videos for --all (default 10).")
    parser.add_argument("--force", action="store_true", help="Regenerate this fingerprint's embeddings; may incur additional usage.")
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    try:
        require_local_extraction()
        ids = [extract_video_id(args.video_id if "://" in args.video_id else "https://youtu.be/" + args.video_id)] if args.video_id else islice(video_repository.iter_video_ids(), args.limit)
        failures = total = 0
        for video_id in ids:
            total += 1
            try:
                video = video_repository.get_video(video_id)
                if video is None:
                    raise ApiException(404, "VIDEO_NOT_FOUND", "This video has not been saved in Supabase.")
                result = ensure_indexed(video, force=args.force)
                print(f"{video_id}: {'already indexed' if result.cached else 'indexed'}; chunks={result.chunks}")
            except ApiException as error:
                failures += 1
                print(f"{video_id}: {error.code}: {error.message}", file=sys.stderr)
        print(f"Processed: {total}; Failed: {failures}")
        return 1 if failures else 0
    except ApiException as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
