from dataclasses import dataclass
import math
import os
import time

from app.schemas.error import ApiException


@dataclass(frozen=True)
class AgentSettings:
    history_messages: int = 12
    history_chars: int = 12000
    max_tools: int = 3
    max_model_calls: int = 6
    request_seconds: float = 45
    max_window: float = 600
    point_window: float = 30
    tool_chars: int = 14000
    summary_batch_chars: int = 8000
    summary_max_batches: int = 3

    @classmethod
    def from_env(cls):
        limits = {
            "history_messages": ("CHAT_HISTORY_MESSAGES", 12, 2, 40),
            "history_chars": ("CHAT_HISTORY_CHARS", 12000, 1000, 40000),
            "max_tools": ("AGENT_MAX_TOOL_CALLS", 3, 1, 5),
            "max_model_calls": ("AGENT_MAX_MODEL_CALLS", 6, 2, 60),
            "request_seconds": ("AGENT_REQUEST_BUDGET_SECONDS", 45, 10, 600),
            "max_window": ("TRANSCRIPT_MAX_WINDOW_SECONDS", 600, 1, 1800),
            "point_window": ("TRANSCRIPT_POINT_WINDOW_SECONDS", 30, 1, 120),
            "tool_chars": ("TOOL_MAX_TEXT_CHARS", 14000, 1000, 40000),
            "summary_batch_chars": ("SUMMARY_BATCH_CHARS", 8000, 1000, 16000),
            "summary_max_batches": ("SUMMARY_MAX_BATCHES", 3, 1, 60),
        }
        values = {}
        for field, (key, default, low, high) in limits.items():
            try:
                value = int(os.getenv(key, str(default)))
                if not low <= value <= high:
                    raise ValueError
            except ValueError:
                raise ApiException(500, "CONFIGURATION_ERROR", f"{key} must be between {low} and {high}.") from None
            values[field] = value
        return cls(**values)


class Budget:
    def __init__(self, settings):
        self.settings = settings
        self.deadline = time.monotonic() + settings.request_seconds
        self.model_calls = self.tool_calls = 0

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ApiException(504, "AGENT_TIMEOUT", "Chat reached its time limit. Try a smaller request or precompute the summary locally.")
        return remaining

    def model(self):
        self.remaining()
        if self.model_calls >= self.settings.max_model_calls:
            raise ApiException(422, "AGENT_LIMIT_REACHED", "This request needs too many model calls. Ask a smaller question.")
        self.model_calls += 1

    def tool(self):
        self.remaining()
        if self.tool_calls >= self.settings.max_tools:
            raise ApiException(422, "AGENT_LIMIT_REACHED", "This request needs too many tool calls. Ask a smaller question.")
        self.tool_calls += 1
