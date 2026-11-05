"""python -m app.scripts.ingest_videos videos.txt [--force]"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from app.schemas.error import ApiException
from app.scripts.ingest_video import load_local_environment, print_result
from app.services.ingestion_service import ingest_video


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tubeInsight-ai batch transcript ingestion")
    parser.add_argument("file", type=Path, help="UTF-8 text file with one YouTube URL per line")
    parser.add_argument("--force", action="store_true", help="Refresh existing saved transcripts")
    args = parser.parse_args(argv)
    load_local_environment()
    try:
        lines = args.file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        print("Error: Could not read the UTF-8 URL file.", file=sys.stderr)
        return 1
    saved = cached = failed = 0
    print("tubeInsight-ai Batch Transcript Ingestion\n")
    for number, line in enumerate(lines, start=1):
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        print(f"Line {number}:")
        try:
            result = ingest_video(url, force=args.force)
            print_result(result)
            cached += int(result.cached)
            saved += int(not result.cached)
        except ApiException as exc:
            failed += 1
            print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
        except ValidationError:
            failed += 1
            print("Error [VALIDATION_ERROR]: Extracted captions could not be saved.", file=sys.stderr)
        except Exception:
            failed += 1
            print("Error [INTERNAL_SERVER_ERROR]: Ingestion failed.", file=sys.stderr)
    print(f"Saved: {saved}; Cached: {cached}; Failed: {failed}; Successes: {saved + cached}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
