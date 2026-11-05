# tubeInsight-ai â€” Supabase storage and local ingestion

FastAPI checks Supabase first. In local **auto** mode, submitting a new YouTube
URL automatically fetches real captions directly, validates them, and saves them
before returning success. Cached videos skip YouTube. Vercel and explicitly
production-configured servers read saved captions only. Local and deployed
backends must use the same Supabase project. Chat remains mocked.

## Install

Use Python 3.11+; the pinned official `supabase==2.34.0` SDK requires it.
Local verification uses Python 3.12. From the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Initial setup only; preserve an existing .env and add the new variables.
Copy-Item .env.example .env
```

Activation is optional. On macOS/Linux use `python3` and `.venv/bin/python`.
The official Supabase SDK uses HTTPS; no ORM or direct PostgreSQL driver is added.

## Supabase project and migration

1. Sign in at [Supabase](https://supabase.com/dashboard), choose **New project**,
   and use the Free plan if creating a free organization. Choose a name, database
   password, and region, then wait for provisioning. No project is created
   automatically by this code.
2. Copy the **Project URL** from the **Connect** dialog or Data API settings.
   Use the HTTPS project origin, e.g. `https://your-project.supabase.co`, without
   `/rest/v1` or other paths.
3. In **Settings â†’ API Keys**, create/copy a server-side **Secret key** starting
   with `sb_secret_`. This is not your database password, account access token,
   publishable key, or legacy anon key. See [Supabase's key documentation](https://supabase.com/docs/guides/getting-started/api-keys).
4. Open **SQL Editor â†’ New query**, paste all of
   [001_create_videos.sql](migrations/001_create_videos.sql), and run it as the
   project owner. It creates `public.videos`, enables RLS, revokes public/anon/
   authenticated access, and grants the server role SELECT/INSERT/UPDATE. No
   public policies are created. The trigger preserves `created_at` and advances
   `updated_at` on updates.
5. Open **Table Editor â†’ videos** to inspect saved rows and their JSONB transcript
   arrays after ingestion. Table Editor uses your administrative project access;
   public access remains disabled.

The migration is transactional and can be rerun for this schema. It does not
reconcile an unrelated existing `videos` table with different columns.
Repository validation rejects empty/all-blank transcripts, invalid types,
nonfinite timestamps, and end times before start times. The SQL constraint also
requires a nonempty JSON array. Upserts use `video_id` as the conflict key, do
not delete first, and preserve caption order, gaps, overlaps, and fractional seconds.

## Environment

Edit the untracked `backend/.env` locally:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=sb_secret_your-real-server-side-key
APP_ENV=development
TRANSCRIPT_SOURCE=auto
SUPABASE_TIMEOUT_SECONDS=10
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

Never commit real keys, put them in React, use `VITE_` prefixes, or send them in
public API requests. Both the app and CLI load `backend/.env`; shell variables
have precedence. Missing configuration produces a safe `CONFIGURATION_ERROR`.
Health/Swagger remain usable before Supabase is configured.

`TRANSCRIPT_SOURCE=auto` enables local cache-first extraction and saving through
`POST /api/videos/process`; there is no required manual ingestion step.
`TRANSCRIPT_SOURCE=supabase` reads saved captions only, including locally. If unset,
it defaults to `supabase`; unknown values return `CONFIGURATION_ERROR`.

The server forces cache-only mode when `VERCEL=1`, when `VERCEL_ENV` is
`production`, `preview`, or `development`, or when `APP_ENV` is `production`/`prod`.
These server-side checks override an accidental `auto` setting. CLI and provider
entry points also refuse extraction in these environments. The browser's address
never determines backend policy. Vercel's [system variables](https://vercel.com/docs/environment-variables/system-environment-variables)
identify its runtime, including preview deployments.

Supabase uses a 10-second read/write/pool inactivity timeout, at most 3 seconds
for connection, and no SDK retries. `SUPABASE_TIMEOUT_SECONDS` must be finite, positive, and at most 30.
Redirects, auth persistence, and auth refresh are disabled. Clients close after
each operation. These are inactivity bounds, not a strict overall deadline.

### Current secret-key compatibility

SDK 2.34.0 accepts `sb_secret_` keys but copies its key into `apikey` and
`Authorization: Bearer`. Modern secret keys are not JWTs. Our scoped HTTPX request
hook removes only that exact non-JWT Bearer copy and retains the SDK's `apikey`
header. It does not replace the SDK or silently substitute a legacy key.
Mocked HTTPS tests verify the actual headers. This implementation requires the
current server-side secret format. See [Supabase's key limitations](https://supabase.com/docs/guides/getting-started/api-keys#known-limitations).

## Optional local ingestion CLI

The React Process button performs ingestion automatically in local `auto` mode.
The CLI remains available for batches, explicit refresh, and preparing deployment
data without using the frontend.

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.ingest_video "https://www.youtube.com/watch?v=Gfr50f6ZBvo"
```

The script validates the URL, checks Supabase, skips extraction if already cached,
otherwise fetches original captions locally and upserts the validated record. It
prints the actual segment count, selected language, and saved/cached status.
Unknown title/duration stay null; the thumbnail is built from the actual video ID.

Explicit refresh:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.ingest_video "https://youtu.be/Gfr50f6ZBvo" --force
```

Failed extraction/validation does not overwrite the old transcript. Failed writes
never trigger deletion. A successful refresh atomically replaces the single row.
`--force` can repair a corrupt stored transcript after successful extraction,
but does not bypass database connectivity/configuration failures. A cached HTTP
request returns existing metadata unchanged. Unknown metadata remains null;
no title or duration is fabricated.

Batch ingestion accepts one URL per line in a UTF-8 file. Blank lines and lines
starting with `#` are ignored; URLs are processed independently:

```powershell
Set-Content -LiteralPath videos.txt -Encoding utf8 -Value @("https://youtu.be/Gfr50f6ZBvo", "https://youtu.be/dQw4w9WgXcQ")
.\.venv\Scripts\python.exe -m app.scripts.ingest_videos videos.txt
.\.venv\Scripts\python.exe -m app.scripts.ingest_videos videos.txt --force
```

The summary reports saved/cached/failure/success counts. Exit status is 0 on
success, 1 on failure. Errors contain safe messages, not raw exceptions. No HTTP
ingestion endpoint exists, and ingestion refuses to run in any Vercel or production environment.

### Existing local caption options

The previous watch/short-link/Shorts validator is retained. Manual and automatic
captions are supported. English (including regional tracks) is preferred by
default; manual wins within a preferred language, while English automatic captions
outrank a manual foreign-language track. Other original languages can be selected;
no translation occurs. End time remains caption start plus actual duration.

| Local-only variable | Default |
| --- | --- |
| `YOUTUBE_CAPTION_LANGUAGES` | `en` |
| `YOUTUBE_CAPTION_FALLBACK` | `true` |
| `YOUTUBE_CONNECT_TIMEOUT_SECONDS` | `3` |
| `YOUTUBE_READ_TIMEOUT_SECONDS` | `10` |
| `YOUTUBE_REQUEST_BUDGET_SECONDS` | `30` |

Caption extraction uses direct connections only. No proxy account or credentials
are needed. The provider ignores ambient HTTP proxy settings, caps extraction at
six HTTP sends, allows at most three redirects, and uses the timeouts above.
There are no automatic retries. The request budget bounds new sends and socket
waits; it is not a strict overall wall-clock deadline. YouTube may still block a
local IP or have no captions; these cases return clear errors without saving data.
The selected original caption language is stored internally, without adding an
API field. See the [caption provider documentation](https://github.com/jdepoix/youtube-transcript-api).

## API and local server

Run this from `backend/` using the project's own interpreter, even if another
virtual environment is already activated in your terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open [Swagger](http://localhost:8000/docs), [OpenAPI](http://localhost:8000/openapi.json),
the [API contract](../docs/api-contract.md), or [TypeScript interfaces](../docs/api-types.ts).

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/videos/process -Method Post -ContentType 'application/json' -Body '{"url":"https://youtu.be/Gfr50f6ZBvo"}'
Invoke-RestMethod http://localhost:8000/api/chat/ask -Method Post -ContentType 'application/json' -Body '{"video_id":"Gfr50f6ZBvo","question":"What is this video about?","conversation_id":null}'
```

Processing reads Supabase first and, in local auto mode only, fetches and saves
missing captions before returning. Chat recognizes saved video IDs without a prior
process request and retains its fixed `mode: "mock"` answer. Its first source is
real saved text for citation UI testing, not evidence supporting the mock answer.
In cache-only mode a missing saved video returns `TRANSCRIPT_NOT_CACHED`
(processing) or
`VIDEO_NOT_FOUND` (chat), both 404. Invalid URLs still return 400.

### Local page stays on Processing

Check `http://localhost:8000/api/health` first. It should respond quickly without
accessing Supabase or YouTube. If it hangs, stop the local Uvicorn process and
restart it with the project interpreter shown above. Check the terminal for a
failed reload or missing dependency; an unrelated activated environment may not
contain this backend's requirements.

The frontend defaults to `http://localhost:8000`. If `VITE_API_BASE_URL` is set,
verify it points to the intended backend and restart Vite after changing it.
Video processing, including reading its response body, times out after 60 seconds
to allow a local cache miss to fetch and save captions. Health and chat retain
15-second timeouts. Failures display an error and release the button.

For automatic local processing, set `APP_ENV=development` and
`TRANSCRIPT_SOURCE=auto` in `backend/.env` and restart FastAPI. Paste a new URL and
click Process. It is saved automatically; subsequent requests and the deployed
backend can read it from the same database. If localhost still returns "not
prepared yet", check inherited shell variables, which take precedence over `.env`.
Applying the migration creates the table; the first local auto request fills it.

## Vercel and frontend verification

In the existing **backend project** environment settings add:

- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY` as a Secret/sensitive value
- `APP_ENV=production`
- `TRANSCRIPT_SOURCE=supabase`
- `CORS_ORIGINS` with exact deployed React origin(s)
- Optional `SUPABASE_TIMEOUT_SECONDS=10`

Retain the working Python runtime/entrypoint settings. Dependencies resolve from
`backend/requirements.txt`; the existing ASGI application is `app.main:app`.
This repository snapshot has no tracked Vercel configuration to verify dashboard
settings against. When ready, redeploy the backend with this code and variables.
Variable changes apply to new deployments, as described by [Vercel](https://vercel.com/docs/environment-variables).
No commit, push, deployment, or project creation is automated by this task.

In **Postman**, GET `https://YOUR-BACKEND.vercel.app/api/health`. After local
ingestion, POST `/api/videos/process` with raw JSON
`{ "url": "https://youtu.be/Gfr50f6ZBvo" }`. Expect 200, `ready`, `real`, and the
same saved captions with numeric second timestamps. Repeat to verify persistent
retrieval. Do not send a Supabase key. A valid unprepared ID returns 404
`TRANSCRIPT_NOT_CACHED`, never a YouTube fallback. POST `/api/chat/ask` with that
saved ID, a question, and null conversation ID; expect the unchanged mock response.

Open deployed React, load the prepared URL, inspect transcript/timestamp links,
and send a question. Try an unprepared URL and confirm its readable error. Anita
needs no request, success-schema, component, or environment change if the backend
base URL stays the same. This intentionally supports prepared videos and does
not fetch arbitrary new videos on Vercel.

## Errors and remaining limits

All errors retain `{ "error": { "code": "...", "message": "..." } }`.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `INVALID_YOUTUBE_URL` | Malformed/unsupported URL or ID |
| 404 | `TRANSCRIPT_NOT_CACHED` | Video has not been prepared |
| 404 | `VIDEO_NOT_FOUND` | Chat video is not saved |
| 404 | `CONVERSATION_NOT_FOUND` | Unknown/expired UUID or wrong video |
| 422 | `VALIDATION_ERROR` | Invalid request or record to save |
| 500 | `CONFIGURATION_ERROR` | Missing/invalid backend settings |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected failure |
| 502 | `INVALID_STORED_TRANSCRIPT` | Corrupt captions; reingest locally with `--force` |
| 503 | `DATABASE_UNAVAILABLE` | Supabase network/auth/permission/schema failure |

Local auto processing and the CLI retain the existing YouTube errors, including
`TRANSCRIPT_NOT_AVAILABLE` (404), `VIDEO_UNAVAILABLE` (403/404),
`YOUTUBE_RATE_LIMITED` (429), `YOUTUBE_ACCESS_BLOCKED` (503),
`TRANSCRIPT_FETCH_FAILED` (502), and `TRANSCRIPT_FETCH_TIMEOUT` (504).
Production requests
never contact YouTube on these failures. Database errors do not become cache
misses or fake success. Service logs/output do not include keys, auth headers,
raw database errors, or signed caption URLs.

Videos persist across Vercel instances. **Conversations and history remain in
process memory.** A cold start/different instance can still return
`CONVERSATION_NOT_FOUND`; React already resets that stale ID. Persistent
conversation memory and real answers are not implemented in this phase.

## Automated and optional live checks

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Ordinary tests mock Supabase and YouTube, block unexpected network sends, and need
no real keys. SDK tests exercise real query builders over MockTransport, including
headers, atomic upserts, repeated reads, errors, and cleanup. CLI tests cover
skip/force/batch failures; API tests cover automatic fetch/save, cache reuse,
failed extraction/writes, production and preview guards, health/chat, CORS, and
schemas. Direct-provider tests verify that no proxy configuration is used.

The opt-in local caption test uses `RUN_YOUTUBE_INTEGRATION=1`. The separate live
storage test requires a migrated project, local credentials, and explicit opt-in:

```powershell
$env:RUN_SUPABASE_INTEGRATION='1'
.\.venv\Scripts\python.exe -m pytest tests/test_live_supabase.py -v -s
Remove-Item Env:RUN_SUPABASE_INTEGRATION
```

It may ingest the public test video if missing, then reads its genuine transcript
repeatedly through the repository/API. It never writes fake test captions to your
project. Live project/deployed API/browser verification must be reported separately;
mocked tests do not establish deployment success.

Next: chunk saved captions with their timestamps, persist chunks/embeddings
(for example with Supabase pgvector), retrieve them in LangChain, and ground RAG
answers/citations in stored segments. Add durable conversation/message storage
before relying on cross-instance memory. These future features are not added here.
