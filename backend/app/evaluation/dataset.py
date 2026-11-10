"""Validated, versioned references; unreviewed real cases cannot become scores."""
from pathlib import Path
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.stored_video import StoredVideo
from app.schemas.video import VideoId

DATASETS = Path(__file__).resolve().parents[2] / "evaluation" / "datasets"
TOOLS = {"search_transcript", "get_transcript_segment", "summarize_video"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Turn(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    answerable: bool
    expected_facts: list[str] = Field(default_factory=list)
    expected_range: tuple[float, float] | None = None
    acceptable_tools: list[list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def valid(self):
        if self.expected_range and not 0 <= self.expected_range[0] < self.expected_range[1]:
            raise ValueError("Expected range must be finite, positive and ordered.")
        if any(not seq or any(t not in TOOLS for t in seq) for seq in self.acceptable_tools):
            raise ValueError("Unknown or empty tool expectation.")
        if any(not fact.strip() for fact in self.expected_facts):
            raise ValueError("Reference facts cannot be blank.")
        return self


class Case(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    category: Literal["answerable", "unsupported", "timestamp", "summary", "memory", "tools", "audio"]
    video_id: VideoId | None = None
    reviewed: bool = False
    review_note: str = ""
    transcript_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    turns: list[Turn] = Field(default_factory=list, max_length=3)
    audio_fixture: str | None = None
    reference_text: str | None = None
    expected_error: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.category == "audio":
            if not self.audio_fixture or self.turns or (not self.reference_text and not self.expected_error):
                raise ValueError("Audio cases need a fixture and reference text or expected error.")
        elif not self.video_id or not self.turns:
            raise ValueError("Chat cases need a video and turns.")
        if self.reviewed:
            if not self.review_note.strip():
                raise ValueError("Reviewed references require a review note.")
            if self.category != "audio" and any(t.answerable and not t.expected_facts for t in self.turns):
                raise ValueError("Reviewed answerable turns need factual references.")
        return self


class Dataset(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    revision: str = Field(min_length=1, max_length=80)
    level: Literal["synthetic", "real"]
    description: str
    videos: list[StoredVideo] = Field(default_factory=list)
    cases: list[Case] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if len({c.id for c in self.cases}) != len(self.cases) or len({v.video_id for v in self.videos}) != len(self.videos):
            raise ValueError("Dataset IDs must be unique.")
        if self.level == "synthetic" and any(c.video_id not in {v.video_id for v in self.videos} for c in self.cases if c.category != "audio"):
            raise ValueError("Synthetic cases must reference an included video.")
        if self.level == "real" and self.videos:
            raise ValueError("Load real transcripts privately from Supabase, not from dataset files.")
        if self.level == "real" and any(c.reviewed and c.category != "audio" and not c.transcript_sha256 for c in self.cases):
            raise ValueError("Reviewed real references must pin the original transcript hash.")
        return self


def load_dataset(name: str) -> Dataset:
    path = Path(name)
    if not path.is_file():
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Use an existing dataset path or a bundled dataset name.")
        path = DATASETS / f"{name}.json"
    return Dataset.model_validate_json(path.read_text(encoding="utf-8"))


def transcript_hash(video):
    return hashlib.sha256(video.model_dump_json(include={"video_id", "language", "transcript"}).encode()).hexdigest()
