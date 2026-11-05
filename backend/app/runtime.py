"""Server-side transcript policy; deployment always overrides local auto mode."""

import os

from app.schemas.error import ApiException


def is_cache_only_runtime() -> bool:
    return (
        os.getenv("VERCEL", "").strip() == "1"
        or os.getenv("VERCEL_ENV", "").strip().lower()
        in {"production", "preview", "development"}
        or os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}
    )


def get_transcript_source() -> str:
    source = os.getenv("TRANSCRIPT_SOURCE", "supabase").strip().lower()
    if source not in {"auto", "supabase"}:
        raise ApiException(
            500, "CONFIGURATION_ERROR", "TRANSCRIPT_SOURCE must be auto or supabase."
        )
    return "supabase" if is_cache_only_runtime() else source


def require_local_extraction() -> None:
    # Guard the provider and CLI too, so a future caller cannot bypass the router.
    if is_cache_only_runtime():
        raise ApiException(
            500, "CONFIGURATION_ERROR",
            "YouTube extraction is local-only and cannot run in production or on Vercel.",
        )
