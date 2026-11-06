"""Strict YouTube URL validation shared by HTTP processing and the local CLI."""

import re
from urllib.parse import parse_qs, urlsplit

from app.schemas.error import ApiException

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}", flags=re.ASCII)


def extract_video_id(url: str) -> str:
    """Allow only exact YouTube hosts and supported paths with one valid ID."""
    invalid = ApiException(
        400, "INVALID_YOUTUBE_URL", "Please provide a valid YouTube URL."
    )
    # urlsplit silently strips some control characters; reject them beforehand.
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        raise invalid
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in _YOUTUBE_HOSTS | _SHORT_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            raise invalid

        if parsed.hostname in _SHORT_HOSTS:
            match = re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", parsed.path)
            video_id = match.group(1) if match else ""
        elif parsed.path == "/watch":
            values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
            video_id = values[0] if len(values) == 1 else ""
        else:
            match = re.fullmatch(r"/shorts/([A-Za-z0-9_-]{11})/?", parsed.path)
            video_id = match.group(1) if match else ""
    except ValueError:
        raise invalid from None

    if _VIDEO_ID.fullmatch(video_id) is None:
        raise invalid
    return video_id

