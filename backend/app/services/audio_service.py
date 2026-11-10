"""Bounded file transcription. No translation, persistence, or provider retries."""
from dataclasses import dataclass
from io import BytesIO
import math
import os
import re
import struct
import wave

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError

from app.agent.observability import observe_request, operation
from app.schemas.audio import TranscriptionResponse
from app.schemas.error import ApiException

FORMATS = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"}


@dataclass(frozen=True)
class AudioSettings:
    max_bytes: int
    model: str
    timeout: float

    @classmethod
    def from_env(cls):
        try:
            mb = float(os.getenv("MAX_AUDIO_UPLOAD_MB", "4"))
            timeout = float(os.getenv("AUDIO_TIMEOUT_SECONDS", "20"))
            if not math.isfinite(mb) or not .01 <= mb <= 4 or not math.isfinite(timeout) or not 1 <= timeout <= 30:
                raise ValueError
            model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe").strip()
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", model):
                raise ValueError
        except ValueError:
            raise ApiException(500, "CONFIGURATION_ERROR", "Check OPENAI_TRANSCRIPTION_MODEL, MAX_AUDIO_UPLOAD_MB (0.01–4), and AUDIO_TIMEOUT_SECONDS (1–30).") from None
        return cls(int(mb * 1_000_000), model, timeout)


def validate_audio(data: bytes, filename: str, settings: AudioSettings):
    if not data:
        raise ApiException(400, "AUDIO_EMPTY", "The audio file is empty.")
    if len(data) > settings.max_bytes:
        raise ApiException(413, "AUDIO_TOO_LARGE", "The recording exceeds the configured audio upload limit.")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in FORMATS:
        raise ApiException(415, "AUDIO_UNSUPPORTED_FORMAT", "Use MP3, MP4, MPEG, MPGA, M4A, WAV, or WebM audio.")
    valid = False
    if extension == "wav":
        try:
            with wave.open(BytesIO(data), "rb") as audio:
                width, channels, frames = audio.getsampwidth(), audio.getnchannels(), audio.getnframes()
                samples = audio.readframes(frames)
                valid = frames > 0 and channels > 0 and len(samples) == frames * width * channels
                if valid and (not any(samples) if width != 1 else all(v == 128 for v in samples)):
                    raise ApiException(422, "AUDIO_NO_SPEECH", "No intelligible speech was detected.")
        except (wave.Error, EOFError, ValueError, struct.error):
            valid = False
    elif extension == "webm":
        header = data[:65536]
        valid = data.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in header and any(x in header for x in (b"A_OPUS", b"A_VORBIS")) and b"\x1f\x43\xb6\x75" in data
    elif extension in {"m4a", "mp4"}:
        valid = len(data) >= 24 and data[4:8] == b"ftyp" and 8 <= int.from_bytes(data[:4], "big") <= len(data) and b"mdat" in data and b"moov" in data
    else:
        # Skip an ID3v2 tag, then require an MPEG audio frame header. A tag alone
        # is not audio. Deep codec validation remains the provider's responsibility.
        offset = 0
        if data.startswith(b"ID3") and len(data) >= 10:
            if any(v & 128 for v in data[6:10]):
                offset = len(data)
            else:
                offset = 10 + sum(v << shift for v, shift in zip(data[6:10], (21, 14, 7, 0)))
        for i in range(offset, min(offset + 4096, len(data) - 4)):
            a, b, c = data[i:i+3]
            if a == 255 and b & 224 == 224 and b & 24 != 8 and b & 6 and c & 240 not in (0, 240) and c & 12 != 12:
                valid = True
                break
    if not valid:
        raise ApiException(422, "AUDIO_INVALID", "The recording is corrupted or does not match its audio format.")
    return extension


def transcribe_audio(data: bytes, filename: str) -> TranscriptionResponse:
    settings = AudioSettings.from_env()
    extension = validate_audio(data, filename, settings)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or any(c.isspace() for c in key):
        raise ApiException(500, "CONFIGURATION_ERROR", "Configure OPENAI_API_KEY on the backend.")
    # Use a fixed filename: user filenames, file content, keys and raw provider
    # exceptions never enter logs or LangSmith. The SDK closes with its client.
    try:
        with observe_request(None, name="audio.request"), operation("audio.transcription", "llm"):
            with OpenAI(api_key=key, timeout=settings.timeout, max_retries=0) as client:
                result = client.audio.transcriptions.create(model=settings.model,
                    file=(f"question.{extension}", data), response_format="json")
    except APITimeoutError:
        raise ApiException(504, "AUDIO_TIMEOUT", "Audio transcription timed out. Try a shorter recording.") from None
    except APIConnectionError:
        raise ApiException(503, "AUDIO_UNAVAILABLE", "Audio transcription is unavailable. Try again later.") from None
    except APIStatusError as error:
        status = error.status_code
        if status == 429:
            raise ApiException(429, "AUDIO_RATE_LIMITED", "Audio transcription is rate limited. Try again later.") from None
        if status in (401, 403, 404):
            raise ApiException(503, "AUDIO_UNAVAILABLE", "Check the backend transcription model and OpenAI account configuration.") from None
        if status in (400, 422):
            raise ApiException(422, "AUDIO_INVALID", "The provider could not read this recording. Try a new recording.") from None
        raise ApiException(502, "AUDIO_TRANSCRIPTION_FAILED", "Audio transcription failed. Try again later.") from None
    except ApiException:
        raise
    except Exception:
        raise ApiException(502, "AUDIO_TRANSCRIPTION_FAILED", "Audio transcription failed. Try again later.") from None
    text = getattr(result, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ApiException(422, "AUDIO_NO_SPEECH", "No intelligible speech was detected.")
    # The current model returns a languages array. Only a single explicit code
    # maps unambiguously to this API's singular language field.
    languages = getattr(result, "languages", None)
    language = None
    if isinstance(languages, list) and len(languages) == 1:
        item = languages[0]
        code = item.get("code") if isinstance(item, dict) else getattr(item, "code", None)
        if isinstance(code, str) and re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", code):
            language = code
    return TranscriptionResponse(text=text.strip(), language=language, model=settings.model)
