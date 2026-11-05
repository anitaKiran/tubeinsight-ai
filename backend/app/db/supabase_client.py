"""Official Supabase SDK with server-only secret keys and bounded HTTPS calls."""

import logging
import math
import os
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx
from supabase import ClientOptions, create_client

from app.schemas.error import ApiException

logger = logging.getLogger(__name__)


def configuration_error(message: str) -> ApiException:
    return ApiException(500, "CONFIGURATION_ERROR", message)


def read_settings() -> tuple[str, str, float]:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise configuration_error("Configure SUPABASE_URL and SUPABASE_SECRET_KEY on the backend.")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
            and parsed.port in {None, 443} and not any(c.isspace() for c in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise configuration_error("SUPABASE_URL must be an HTTPS project origin without credentials or a path.")
    if not key.startswith("sb_secret_") or len(key) <= len("sb_secret_") or any(
        c.isspace() or ord(c) < 32 for c in key
    ):
        raise configuration_error("SUPABASE_SECRET_KEY must be a current server-side sb_secret_ key.")
    try:
        timeout = float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "10"))
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError
    except ValueError:
        raise configuration_error("SUPABASE_TIMEOUT_SECONDS must be greater than 0 and at most 30.") from None
    return url.rstrip("/"), key, timeout


@contextmanager
def get_supabase_client():
    url, key, seconds = read_settings()

    def remove_non_jwt_bearer(request: httpx.Request) -> None:
        # SDK 2.34 copies the API key into Authorization. Modern secret keys are
        # not JWTs: retain the SDK's apikey header and remove only that exact copy.
        if request.headers.get("Authorization") == f"Bearer {key}":
            del request.headers["Authorization"]

    try:
        with httpx.Client(
            timeout=httpx.Timeout(seconds, connect=min(3.0, seconds)),
            follow_redirects=False,
            event_hooks={"request": [remove_non_jwt_bearer]},
        ) as transport:
            client = create_client(url, key, options=ClientOptions(
                auto_refresh_token=False, persist_session=False,
                httpx_client=transport, postgrest_client_retry=False,
                postgrest_client_timeout=transport.timeout,
            ))
            yield client
    except ApiException:
        raise
    except Exception as exc:
        # Never log raw SDK/HTTP errors, response bodies, keys, or auth headers.
        logger.warning("Supabase operation failed: type=%s", type(exc).__name__)
        raise ApiException(503, "DATABASE_UNAVAILABLE", "Transcript storage is unavailable. Try again later.") from None
