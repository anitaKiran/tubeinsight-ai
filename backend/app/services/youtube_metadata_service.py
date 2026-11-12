"""Best-effort public YouTube oEmbed metadata; never scrape or guess titles."""
from dataclasses import dataclass
import json
import logging
import math
import os
import re
from urllib.parse import urlsplit

import httpx

from app.schemas.error import ApiException

logger = logging.getLogger(__name__)
ENDPOINT = "https://www.youtube.com/oembed"
MAX_RESPONSE_BYTES = 64_000


def validate_id(video_id):
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ApiException(400, "INVALID_YOUTUBE_URL", "Please provide a valid YouTube video ID.")


def missing(value):
    return value is None or isinstance(value, str) and not value.strip()


@dataclass(frozen=True)
class VideoMetadata:
    title: str
    thumbnail_url: str | None = None


def valid_thumbnail(value, video_id):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.hostname in {"i.ytimg.com", "img.youtube.com"}
            and url.username is None and url.password is None and url.port in {None,443}
            and not url.fragment and not any(c.isspace() for c in value)
            and re.fullmatch(rf"/(?:vi|vi_webp)/{re.escape(video_id)}/[A-Za-z0-9_.-]+",url.path)):
            return value
    except ValueError:
        pass
    return None


def fetch_metadata(video_id: str) -> VideoMetadata | None:
    validate_id(video_id)
    if os.getenv("YOUTUBE_METADATA_ENABLED", "true").strip().lower() not in {"true", "1"}:
        return None
    try:
        seconds = float(os.getenv("YOUTUBE_METADATA_TIMEOUT_SECONDS", "4"))
        if not math.isfinite(seconds) or not 1 <= seconds <= 10:
            raise ValueError
    except ValueError:
        logger.warning("Video metadata unavailable: video=%s reason=invalid_timeout_configuration",video_id)
        return None
    reason = "unavailable"
    try:
        # One attempt, no redirects/environment proxy or user-controlled host.
        with httpx.Client(timeout=httpx.Timeout(seconds,connect=min(2,seconds)),follow_redirects=False,trust_env=False) as client:
            with client.stream("GET",ENDPOINT,params={"url":f"https://www.youtube.com/watch?v={video_id}","format":"json"},
                headers={"Accept":"application/json"}) as response:
                if response.status_code != 200:
                    reason = f"provider_http_{response.status_code}"
                elif response.headers.get("content-type", "").split(";",1)[0].strip().lower() != "application/json":
                    reason = "invalid_response_type"
                else:
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        if len(content)+len(chunk)>MAX_RESPONSE_BYTES:
                            raise ValueError("oversized metadata")
                        content.extend(chunk)
                    data=json.loads(content)
                    if not isinstance(data,dict) or data.get("type")!="video" or data.get("version")!="1.0" or data.get("provider_name")!="YouTube":
                        raise ValueError("invalid metadata")
                    title=data.get("title")
                    if not isinstance(title,str) or not title.strip() or len(title)>1000 or any(ord(c)<32 for c in title):
                        raise ValueError("invalid title")
                    return VideoMetadata(title.strip(),valid_thumbnail(data.get("thumbnail_url"),video_id))
    except httpx.TimeoutException:
        reason="timeout"
    except (ValueError,UnicodeError):
        reason="invalid_response"
    except Exception:
        reason="connection_or_provider_failure"
    # Never log exceptions, response bodies, titles, keys or signed URLs.
    logger.warning("Video metadata unavailable: video=%s reason=%s",video_id,reason)
    return None
