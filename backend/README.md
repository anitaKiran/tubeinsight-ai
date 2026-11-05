# tubeInsight-ai backend — Phase 1

FastAPI now retrieves real YouTube captions. Chat remains a fixed, explicitly
simulated response. No LLM, RAG, audio downloads, transcription model, or database
integration is added. Optional Webshare proxy routing is enabled only when both
backend proxy credentials are configured.

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
| `WEBSHARE_PROXY_USERNAME` | empty | Optional Webshare proxy username; requires password |
| `WEBSHARE_PROXY_PASSWORD` | empty | Optional Webshare proxy password; requires username |

Timeout values must be finite, positive, and at most 120 seconds. A new Session
is created and closed for each extraction because the library's Session is not
thread-safe. Requests use the smaller of the configured timeout and remaining
budget, at most six HTTP sends and three redirects. Direct mode does not retry.
Webshare mode permits at most two extraction attempts (one retry), sharing the
same Session, deadline, and six-send cap. The library's nested adapter/blocked
retries are disabled with `retries_when_blocked=0`, rather than using its default
of ten. Each new proxy connection can rotate its residential exit IP; the built-in
configuration sets `Connection: close`. Explicit Webshare routing takes precedence
over ambient `HTTP_PROXY`/`HTTPS_PROXY` variables.
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

A library `IpBlocked` can represent HTTP 429 or CAPTCHA/IP refusal in version
1.2.4. It cannot reliably distinguish temporary rate limiting from an IP block.
The optional single Webshare retry is bounded; clients should not add rapid
retry loops on 429 or 503. Proxy connection/authentication failures and exhausted
transport retries return 502 `TRANSCRIPT_FETCH_FAILED`; timeout exhaustion returns
504, and persistent blocking retains the existing 429/503 codes. A partial pair
of proxy credentials returns 500 `INTERNAL_SERVER_ERROR` with a safe message
naming the two required variables. It does not reveal their values. Failures never return
HTTP 200 or a synthetic transcript. Swagger documents all endpoint errors.

## Tests

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

The ordinary suite mocks the public caption client and blocks unexpected external
requests. It covers normalization, fractional timestamps/overlaps, original text,
manual/automatic language choice, empty/missing captions, upstream errors,
finite timeouts and request limits, optional proxy setup/retry exhaustion,
credential-safe errors/logging, URL validation, schema/OpenAPI, CORS, health,
mock chat, and lost in-memory state. Proxy tests use fake credentials and mocked
transport/caption calls. The ordinary suite overrides proxy variables even when
a developer's `.env` contains real values. No purchased proxy access is needed.
The optional live check is skipped by default.

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

## Optional Webshare rotating residential proxy

Use the library's built-in `WebshareProxyConfig` with your existing **rotating
residential** proxy credentials. The maintainer's [Webshare instructions](https://github.com/jdepoix/youtube-transcript-api#using-webshare)
distinguish this from static residential/proxy-server products. This application
does not purchase, provision, or activate a proxy subscription.

Add the following to your untracked `backend/.env`, replacing the placeholders
with the **proxy username/password** from Webshare's proxy settings (not your
Webshare dashboard login or an API key):

```dotenv
WEBSHARE_PROXY_USERNAME=your-proxy-username
WEBSHARE_PROXY_PASSWORD=your-proxy-password
```

Restart the local backend. Both unset/empty/whitespace-only values preserve
direct caption retrieval. Exactly one nonblank value is a configuration error;
requests do not silently use direct retrieval in that case. Both nonblank values
enable Webshare. Language preferences, segment normalization, API payloads, and
mock chat behavior remain the same. No extra dependency is needed beyond the
existing pinned `youtube-transcript-api` package.

For transient proxy connection errors, blocked/rate-limited requests, or timeouts,
the provider can retry extraction once, provided time and HTTP-send capacity
remain. It never falls back to direct retrieval after a proxy failure, resets
its budget, or fabricates captions. Missing captions, unavailable videos, malformed
data, and required upstream PO tokens are not retried. A proxy cannot guarantee
YouTube acceptance, so persistent blocking is still reported honestly.

Only transport labels (`direct`/`webshare`), video ID, caption language, and
exception class names are used in provider logs. Credentials, proxy URLs,
authorization headers, and raw upstream exceptions are not logged or returned.
Keep these variables on the backend, never under a `VITE_` prefix, and never
commit `.env` or paste credentials into curl commands or screenshots.

### Configure and verify on Vercel

1. Open the **backend** Vercel project, then **Settings → Environment Variables**.
   Add `WEBSHARE_PROXY_USERNAME` and `WEBSHARE_PROXY_PASSWORD` as secret/sensitive
   values where the dashboard supports that choice. Select Production and any
   Preview environment in which proxy access is intended. Keep both variables
   in the same scope and check for branch-specific overrides. Do not add these
   credentials to the separate React project.
2. Retain the existing language/timeouts/CORS configuration. Defaults remain
   3-second connection, 10-second read inactivity, and 30-second shared send
   budget; choose a Vercel function duration that accommodates these waits.
   The read timeout is not a strict wall-clock deadline.
3. When you choose to deploy, include this code and create a new deployment after
   adding the variables. Existing deployments do not inherit changed environment
   variables; see [Vercel's documentation](https://vercel.com/docs/environment-variables).
   This task does not commit, push, or deploy automatically.
4. Check the new deployment's health, then submit a public captioned video using
   the existing endpoint. This PowerShell example sends no proxy credentials to
   the HTTP API:

```powershell
$backendUrl = 'https://YOUR-BACKEND.vercel.app'
Invoke-RestMethod "$backendUrl/api/health"
$result = Invoke-RestMethod "$backendUrl/api/videos/process" -Method Post -ContentType 'application/json' -Body '{"url":"https://www.youtube.com/watch?v=Gfr50f6ZBvo"}'
$result.status
$result.mode
$result.video.id
$result.transcript.Count
$result.transcript | Select-Object -First 3
```

Expect HTTP 200, `status: "ready"`, `mode: "real"`, the requested video ID, and
nonempty original caption text with numeric second timestamps. Try another public
captioned video if that video's captions become unavailable. The response schema
does not add proxy details. To confirm Webshare routing, correlate the request
with Webshare usage and, if application INFO logging is enabled, the safe success
log's `transport=webshare`. A response with `mode: "real"` alone does not establish
which transport was used. Keep detailed HTTP wire/header logging disabled.

For 500, check that both variable names/scopes are correct. For 502, check proxy
credentials, plan access, availability, and exhausted attempts. For 504, inspect
latency and bounded timeout settings. For persistent 429/503, the exit IP may still
be rejected. Review safe error codes and retry later rather than creating a
client retry storm. `/api/health` only checks connectivity; it does not test the
proxy or prove that caption extraction succeeded.

A real Webshare/Vercel smoke test requires your configured deployment and proxy
account. Mocked tests verify routing and error handling, not production proxy
availability. Proxy support also does not solve process-local video/conversation
storage across Vercel instances.

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
Webshare routing is optional and requires manually configured credentials as
described above; no provider is provisioned and no cookie authentication is added.

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
