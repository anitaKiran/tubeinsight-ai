# tubeInsight-ai backend — Phase 1

FastAPI now retrieves real YouTube captions. Chat remains a fixed, explicitly
simulated response. No LLM, RAG, audio downloads, transcription model, database,
or paid transcript/proxy service is used.

## Install and run

Python 3.11+ is supported by the code; local verification used Python 3.12.
From the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Optional: copy only if you do not already have a local .env.
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

For an existing environment, keep your `.env` and run the pip command again.
On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python`.

- Base URL: <http://localhost:8000>
- Swagger: <http://localhost:8000/docs>
- OpenAPI: <http://localhost:8000/openapi.json>
- [API contract](../docs/api-contract.md) and [TypeScript interfaces](../docs/api-types.ts)

## API behavior

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Existing connectivity response, kept compatible |
| POST | `/api/videos/process` | Real captions, `mode: "real"`, nullable title/duration |
| POST | `/api/chat/ask` | Fixed simulated answer, `mode: "mock"` |

The existing URL validator is unchanged: watch, `youtu.be`, and Shorts URLs on
exact allowed YouTube domains, with valid 11-character IDs. Credentials,
lookalike domains, explicit ports, and malformed URLs/IDs are rejected.

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/videos/process -Method Post -ContentType 'application/json' -Body '{"url":"https://www.youtube.com/watch?v=Gfr50f6ZBvo"}'
Invoke-RestMethod http://localhost:8000/api/chat/ask -Method Post -ContentType 'application/json' -Body '{"video_id":"Gfr50f6ZBvo","question":"What is this video about?","conversation_id":null}'
```

Equivalent Bash curl examples:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/videos/process -H 'Content-Type: application/json' -d '{"url":"https://youtu.be/Gfr50f6ZBvo"}'
curl http://localhost:8000/api/chat/ask -H 'Content-Type: application/json' -d '{"video_id":"Gfr50f6ZBvo","question":"What is this video about?","conversation_id":null}'
```

## Caption extraction and language selection

`video_service.py` validates the URL and passes only its video ID to
`youtube_transcript_service.py`. The provider uses the installed
`youtube-transcript-api` 1.2.4 public instance API: `YouTubeTranscriptApi(...).list(id)`
and the selected track's `fetch(preserve_formatting=False)` method. No deprecated
static `get_transcript` calls are used.

English captions, including regional English tracks, are preferred by default.
Manual captions win over automatic ones within a preferred language. An automatic
English track wins over a manual foreign-language track. If no preferred language
exists and fallback is enabled, the first manual track (otherwise first automatic
track) is used in its original language. Tracks are never translated. Text is the
library's plain caption text; no text is invented, summarized, or filled in.

Each segment preserves provider order and uses `end_seconds = start + duration`.
Gaps and overlaps remain intact; a caption's end is not replaced by the next
caption's start. Empty/all-blank results return an error. Only successful results
are stored and returned as `ready`. No dummy-transcript fallback exists.

See the [maintainer's API documentation](https://github.com/jdepoix/youtube-transcript-api).

## Metadata investigation

Title and duration are intentionally `null` in this phase. The caption library
does not provide reliable video metadata. A later, independent best-effort
metadata step could use YouTube's registered [oEmbed endpoint](https://oembed.com/providers.json)
for title/author information. The official [YouTube Data API videos resource](https://developers.google.com/youtube/v3/docs/videos/list)
can supply richer metadata with separate API configuration and quota management.
No extra metadata request or credential is introduced here. Transcript retrieval
never depends on metadata availability, and caption end times are not presented
as a video's duration. The existing thumbnail pattern is unchanged.

## Configuration

`backend/.env` is loaded by the app; shell variables take precedence.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Exact comma-separated React origins |
| `YOUTUBE_CAPTION_LANGUAGES` | `en` | Ordered comma-separated preferred language codes, e.g. `en,de` |
| `YOUTUBE_CAPTION_FALLBACK` | `true` | Allow another available original language |
| `YOUTUBE_CONNECT_TIMEOUT_SECONDS` | `3` | Per-send connection timeout |
| `YOUTUBE_READ_TIMEOUT_SECONDS` | `10` | Per-send read inactivity timeout |
| `YOUTUBE_REQUEST_BUDGET_SECONDS` | `30` | Budget checked before each HTTP send |

Timeout values must be finite, positive, and at most 120 seconds. A new Session
is created and closed for each extraction because the library's Session is not
thread-safe. Requests use the smaller of the configured timeout and remaining
budget, at most six HTTP sends and three redirects, and no automatic retries.
The budget is not a hard wall-clock cancellation of an in-flight response:
Requests read timeouts measure inactivity. Set the platform function duration
above the expected retrieval time and test it from the deployment region.

Use explicit production `CORS_ORIGINS`; wildcards and paths are rejected. An
empty value disables cross-origin access. Restart after configuration changes.

## Error responses

Every application failure uses `{ "error": { "code": "...", "message": "..." } }`.
No upstream HTML, credentials, stack traces, or raw library errors are returned.

| HTTP | Code | Situation |
| --- | --- | --- |
| 400 | `INVALID_YOUTUBE_URL` | Invalid URL or video ID |
| 403 | `VIDEO_UNAVAILABLE` | Private, age-restricted, or unplayable video |
| 404 | `VIDEO_UNAVAILABLE` | Missing/removed video |
| 404 | `TRANSCRIPT_NOT_AVAILABLE` | Captions disabled/missing/empty or no allowed language |
| 429 | `YOUTUBE_RATE_LIMITED` | Upstream HTTP 429 / library `IpBlocked` |
| 502 | `TRANSCRIPT_FETCH_FAILED` | Upstream network or caption parsing failure |
| 503 | `YOUTUBE_ACCESS_BLOCKED` | Bot/IP blocking, upstream HTTP 403, or required PO token |
| 504 | `TRANSCRIPT_FETCH_TIMEOUT` | Upstream timeout or exhausted send budget |
| 404 | `VIDEO_NOT_FOUND` | Mock chat cannot find processed video in this process |
| 404 | `CONVERSATION_NOT_FOUND` | Conversation absent or bound to a different video |
| 422 | `VALIDATION_ERROR` | Missing/invalid request fields or malformed JSON |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected application failure |

A library `IpBlocked` means HTTP 429 in version 1.2.4; it cannot reliably tell
whether that refusal is temporary rate limiting or an IP reputation block.
Neither 429 nor 503 should trigger rapid automatic retries. Failures never return
HTTP 200 or a synthetic transcript. Swagger documents all endpoint errors.

## Tests

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

The ordinary suite mocks the public caption client and blocks unexpected external
requests. It covers normalization, fractional timestamps/overlaps, original text,
manual/automatic language choice, empty/missing captions, upstream errors,
finite timeouts and request limits, URL validation, schema/OpenAPI, CORS, health,
mock chat, and lost in-memory state. The optional live check is skipped by default.

To explicitly make real YouTube requests:

```powershell
$env:RUN_YOUTUBE_INTEGRATION = '1'
$env:YOUTUBE_TEST_VIDEO_ID = 'Gfr50f6ZBvo' # Replace with another public captioned video.
.\.venv\Scripts\python.exe -m pytest tests/test_live_transcript.py -v -s
Remove-Item Env:RUN_YOUTUBE_INTEGRATION
```

On Bash prefix the command with `RUN_YOUTUBE_INTEGRATION=1 YOUTUBE_TEST_VIDEO_ID=Gfr50f6ZBvo`.
The live test validates the process response and mock chat. It intentionally fails
if YouTube is blocked, unavailable, or has removed that video's captions.

## Vercel considerations and remaining limitations

This repository snapshot contains no tracked `vercel.json`, `pyproject.toml`,
Python version selector, or Vercel project link. Existing dashboard root directory,
entrypoint, runtime, duration, environment variables, and deployed region could
not be verified from source. Keep the working deployment settings; do not replace
them based on local success alone. For separate projects the backend dependencies
must resolve from `backend/requirements.txt`; confirm the configured entrypoint
loads the existing `app.main:app` ASGI application. The normal backend root is
`backend/`, with React deployed separately from `frontend/`.

Only lightweight Python HTTP/XML dependencies were added. The code does not
require a browser, FFmpeg, ML models, video downloads, or persistent filesystem
writes. Verify the selected Vercel Python runtime and exact production/preview
CORS origins. See [Vercel's FastAPI guide](https://vercel.com/docs/frameworks/backend/fastapi)
and [Python runtime documentation](https://vercel.com/docs/functions/runtimes/python).

The [caption library documents cloud IP blocking](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception).
Local extraction working does not establish that extraction works from Vercel.
If deployed requests return `YOUTUBE_ACCESS_BLOCKED` or repeated 429s, options to
assess separately include a permitted caption worker on a different network,
an approved transcript provider, or an explicitly approved proxy arrangement.
No paid service, proxy credentials, or cookie authentication is configured here.

Processed videos and conversations still live in per-process dictionaries.
A warm instance may retain them; another instance or a cold start will not.
Processing can succeed on instance A and the immediately following chat on B can
return `VIDEO_NOT_FOUND`. A follow-up can return `CONVERSATION_NOT_FOUND` after
state is lost. This is a real deployment limitation, not a successful persistent
chat implementation. The API reports these errors instead of fabricating state.

Next phase: add a shared persistent repository, for example PostgreSQL with a
video table keyed by video ID, original caption segments/language/version stored
with metadata, conversations tied to videos, and ordered message turns. All
processing/chat requests must read the shared store. Then chunk persisted
transcripts without losing start/end times, embed/index the chunks, and add RAG
answers with citations back to those stored timestamps. None of that is
implemented in Phase 1.
