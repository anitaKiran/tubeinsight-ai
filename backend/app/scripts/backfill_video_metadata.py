"""Manual, bounded metadata-only repair; dry-run unless --apply is supplied."""
import argparse
import sys
import time

from app.repositories import video_repository as repo
from app.scripts.ingest_video import load_local_environment
from app.services import youtube_metadata_service as provider
from app.schemas.error import ApiException


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--apply",action="store_true",help="Fetch metadata and conditionally PATCH missing fields")
    group.add_argument("--dry-run",action="store_true",help="List candidates only; no metadata requests or writes (default)")
    parser.add_argument("--limit",type=int,default=100,help="Maximum rows scanned, 1–500; includes valid-title skips")
    parser.add_argument("--video-id",help="Repair only this saved video")
    parser.add_argument("--after-video-id",help="Resume keyset scan after this ID")
    parser.add_argument("--delay-seconds",type=float,default=.5,help="Delay between provider attempts, 0.25–5")
    args=parser.parse_args(argv)
    if not 1<=args.limit<=500 or not .25<=args.delay_seconds<=5 or args.video_id and args.after_video_id:
        parser.error("Use limit 1–500, delay 0.25–5, and either --video-id or --after-video-id.")
    load_local_environment()
    scanned=skipped=candidates=updated=failed=attempts=0
    last=None
    print("tubeInsight-ai metadata backfill: APPLY" if args.apply else "tubeInsight-ai metadata backfill: DRY RUN (no provider calls or writes)")
    try:
        if args.video_id:provider.validate_id(args.video_id)
        if args.after_video_id:provider.validate_id(args.after_video_id)
        if args.video_id:
            row=repo.get_video_metadata(args.video_id)
            if row is None:
                raise ApiException(404,"VIDEO_NOT_FOUND","This video has not been saved.")
            rows=iter([row])
        else:
            rows=repo.iter_video_metadata(batch_size=min(args.limit,100),after_video_id=args.after_video_id)
        # islice avoids fetching an extra page when the explicit scan limit ends.
        from itertools import islice
        for row in islice(rows,args.limit):
            scanned+=1;last=row["video_id"];provider.validate_id(last)
            if not provider.missing(row.get("title")):
                skipped+=1;print(f"{last}: skipped (title already present)");continue
            candidates+=1
            if not args.apply:
                print(f"{last}: would fetch and repair missing metadata");continue
            if attempts:time.sleep(args.delay_seconds)
            attempts+=1
            try:
                metadata=provider.fetch_metadata(last)
                if metadata is None:
                    failed+=1;print(f"{last}: metadata unavailable",file=sys.stderr);continue
                current=repo.get_video(last)
                if current is None:
                    failed+=1;print(f"{last}: saved video no longer available",file=sys.stderr);continue
                if not provider.missing(current.title):
                    skipped+=1;print(f"{last}: skipped (concurrently repaired)");continue
                confirmed=repo.repair_missing_metadata(current,metadata.title,metadata.thumbnail_url)
                if provider.missing(confirmed.title):
                    failed+=1;print(f"{last}: update unconfirmed",file=sys.stderr)
                else:
                    updated+=1;print(f"{last}: title persisted (transcript untouched)")
            except Exception:
                failed+=1;print(f"{last}: metadata update failed",file=sys.stderr)
    except ApiException as error:
        print(f"Error [{error.code}]: {error.message}",file=sys.stderr);return 1
    except Exception:
        print("Error: metadata scan could not complete; no transcript operations were requested.",file=sys.stderr);return 1
    print(f"Scanned: {scanned}; Candidates: {candidates}; Updated: {updated}; Skipped: {skipped}; Failed: {failed}")
    if last:print(f"Last scanned ID: {last}")
    return 1 if failed else 0


if __name__=="__main__":
    raise SystemExit(main())
