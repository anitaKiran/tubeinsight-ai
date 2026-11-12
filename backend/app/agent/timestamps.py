"""Validated timestamps and exact chronological overlap lookup on saved captions."""
import math
import re

from app.schemas.error import ApiException


def seconds(value):
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp.")
    if isinstance(value, (float, int)):
        result = float(value)
    elif isinstance(value, str):
        raw = value.strip().lower()
        if ":" in raw:
            parts = raw.split(":")
            if len(parts) not in {2, 3} or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
                raise ValueError("Use MM:SS or HH:MM:SS.")
            numbers = [float(p) for p in parts]
            if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
                raise ValueError("Timestamp components must be valid.")
            result = sum(number * 60 ** i for i, number in enumerate(reversed(numbers)))
        else:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hours?)?", raw)
            if not match:
                raise ValueError("Use seconds, minutes, MM:SS, or HH:MM:SS.")
            amount, unit = match.groups()
            result = float(amount) * (3600 if unit and unit.startswith("h") else 60 if unit and unit.startswith("m") else 1)
    else:
        raise ValueError("Invalid timestamp.")
    if not math.isfinite(result) or result < 0:
        raise ValueError("Timestamp must be finite and non-negative.")
    return result


def select_range(video, start, end, settings):
    if end is None:
        start, end = max(0, start - settings.point_window / 2), start + settings.point_window / 2
    if end <= start or end - start > settings.max_window:
        raise ApiException(422, "INVALID_TIME_RANGE", "Use an increasing, non-negative interval within TRANSCRIPT_MAX_WINDOW_SECONDS.")
    # Half-open intervals: a caption ending exactly at start is outside.
    selected = [s for s in video.transcript if s.end_seconds > start and s.start_seconds < end]
    selected.sort(key=lambda s: (s.start_seconds, s.end_seconds))
    return selected
