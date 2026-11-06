# tubeInsight-ai — Transcript caching and real video RAG

FastAPI checks Supabase first. In local **auto** mode, submitting a new YouTube
URL automatically fetches real captions directly, validates them, and saves them
before returning success. Cached videos skip YouTube. Vercel and explicitly
production-configured servers read saved captions only. Local and deployed
backends must use the same Supabase project and Pinecone index. Chat now uses
LangChain, OpenAI, and Pinecone to answer only from verified video evidence.

## Real RAG setup and indexing

Use the existing **tubechunks** Pinecone index: dense vectors, **1024 dimensions**,
cosine similarity, with the `chunk_text` string field embedded by
**llama-text-embed-v2**. This is the user's selected replacement for the original
OpenAI-embedding/1536-dimensional plan. OpenAI `gpt-6-luna` generates the answers;
Pinecone generates passage and query embeddings using the SAME Llama model.
OpenAI embeddings are not used or mixed into this index. Nothing creates, deletes,
resizes, or changes the index schema.

Add these server-only values to the existing untracked `backend/.env`:

```dotenv
OPENAI_API_KEY=your-private-openai-key
OPENAI_CHAT_MODEL=gpt-6-luna
PINECONE_EMBEDDING_MODEL=llama-text-embed-v2
PINECONE_EMBEDDING_FIELD=chunk_text
PINECONE_EMBEDDING_DIMENSIONS=1024
PINECONE_API_KEY=your-private-pinecone-key
PINECONE_INDEX_NAME=tubechunks
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=180
RAG_EMBED_BATCH_SIZE=32
RAG_TOP_K=4
RAG_MIN_SCORE=0.25
RAG_API_TIMEOUT_SECONDS=10
RAG_INDEX_TIMEOUT_SECONDS=90
RAG_MAX_CHUNKS=2000
```

Keep the existing Supabase keys and local `APP_ENV=development`,
`TRANSCRIPT_SOURCE=auto`. Shell environment variables override `.env`; restart
FastAPI after edits. Missing keys/model/index settings return safe setup errors.
The provider checks the existing embedded-text field, Llama model, dimensions,
cosine metric, stored text, and readiness before writing. Set the same model, dimensions, chunk size,
overlap, and index name on Vercel so fingerprints match.

**Local React workflow:** paste a URL and click Process. Supabase is checked
first; missing captions are fetched directly and saved exactly as before. The
saved transcript is then chunked and indexed before success. Existing saved
videos are indexed too. Repeat processing checks a completion manifest and skips
embeddings. Indexing failures return a clear error while preserving saved captions;
retry processing after fixing the cause. No critical persistence uses background
tasks. Production processing only returns Supabase captions and never indexes.

**Backfill one saved video**, from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.index_cached_videos --video-id Gfr50f6ZBvo
```

This command never calls YouTube. Repeating it is idempotent. `--force` explicitly
regenerates the current version's embeddings and may add usage. Bulk backfill is
an explicit user action; it is never run automatically:

```powershell
.\.venv\Scripts\python.exe -m app.scripts.index_cached_videos --all --limit 10
```

IDs are paged from Supabase without loading all full transcripts at once. Each
video is read and processed independently; failures are reported, and the exit
code is nonzero if any failed. The CLI refuses production/Vercel environments.

### Chunking, idempotency, and evidence

LangChain's recursive character splitter targets 1000 characters with 180-character
overlap and prefers caption/sentence/word boundaries. Character spans map each
chunk to the original contributing segments. Start is their actual minimum start;
end is their actual maximum end. A chunk splitting one long caption retains that
caption's real range; no interpolated timestamps are invented. Pinecone metadata
includes `video_id`, `chunk_index`, `text`, timestamps, character/segment spans,
and a transcript/embedding/chunking fingerprint.

Each video/fingerprint has its own namespace and stable document IDs. Hosted
embeddings are batched (32 documents by default), upserts are idempotent, and interrupted runs reuse
confirmed chunks. A separate completion manifest is written only after all chunk
metadata/text is visible. A changed transcript, model, dimensions, or chunking
setting gets a new isolated namespace; chat never uses stale versions. Old
namespaces are retained to avoid deleting valid data. They consume storage and
can be cleaned administratively after confirming they are unused. Concurrent
indexers in separate processes may duplicate embedding work, though their stable
IDs prevent duplicate stored chunks.

Chat validates the manifest, asks Pinecone to embed the question, and retrieves top-k=4
within that exact namespace plus video/fingerprint/kind metadata filters. Returned
text, timestamps, and identity are checked against freshly read Supabase captions.
Cross-video, tampered, and low-score matches are rejected. The model selects
citation IDs; excerpts and timestamps come from the server, never model quotes.
The relevance threshold is configurable and needs evaluation for your videos.

LangChain LCEL (`ChatPromptTemplate | ChatOpenAI.with_structured_output`) uses the
configured model with native JSON schema and no agent/tools.

`langchain-pinecone==0.2.13` pins Pinecone SDK <8, whose vector endpoints cannot
read this newer document-schema index. `DocumentVectorStore` extends its store
interface with the current documented Pinecone 2026-07 documents API, over bounded
HTTPX calls. This preserves a compatible dependency set and the existing index.
It uses text upserts and `score_by: embed` searches; it never fabricates vectors.
See Pinecone's [upsert](https://docs.pinecone.io/reference/api/2026-07/data-plane/upsert_documents)
and [search](https://docs.pinecone.io/reference/api/2026-07/data-plane/search_documents) APIs. The requested
`gpt-6-luna` supports structured output; the installed integration is tested with
mock HTTP at the SDK boundary. Transcripts are untrusted data, never system
instructions. When evidence is absent or insufficient, the API returns an honest
inability-to-answer message with `sources: []`; it never substitutes a fake answer.

### Real chat verification

From the repo root, start the backend with its own interpreter:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In Postman, POST `http://localhost:8000/api/chat/ask`, Body → raw → JSON:

```json
{
  "video_id": "Gfr50f6ZBvo",
  "question": "What are the main ideas discussed?",
  "conversation_id": null
}
```

Index that saved ID first. Expect `mode: "real"`, a grounded `answer`, a UUID, and
actual `sources` with numeric second timestamps. Reuse the UUID on the same video.
Ask a question absent from the video; expect an inability-to-answer message and
no sources. Try an unindexed different video; expect `VIDEO_NOT_INDEXED`, never
sources from the first video. Invalid/blank questions return the existing 422
format. Questions are bounded to 4000 characters and 8000 UTF-8 bytes.

In React, process the video, ask a question, inspect its excerpts, and click the
existing timestamp links. The layout and history rendering are unchanged; chat
mode types now accept `real`. Local React still defaults to localhost:8000.

### RAG errors, timeouts, and usage

`VIDEO_NOT_INDEXED` (409) means index the current transcript/configuration locally.
`PINECONE_INDEX_NOT_FOUND` / `PINECONE_INDEX_INCOMPATIBLE` (500) explain setup
problems. `RAG_RATE_LIMITED` (429), `RAG_UNAVAILABLE` (503), `RAG_TIMEOUT` (504),
and `RAG_RESPONSE_INVALID` (502) never return a fake successful answer.
`INDEXING_PENDING` (503), `INDEXING_TIMEOUT` (504), or `INDEXING_LIMIT_EXCEEDED`
(422) preserve the Supabase transcript. All retain `error.code`/`error.message`.

Provider requests default to 10-second socket timeouts. OpenAI retries at most
once; Pinecone document calls are not retried automatically. Pinecone visibility polls are
limited to four attempts. The local indexing budget (90 seconds) is checked
between bounded operations, not a strict wall-clock interrupt. UI processing
has a 180-second deadline, chat 90 seconds, and health 15 seconds. Long videos
may need a higher local budget/limit or explicit CLI retries; no serverless chat
request indexes a full video. Failed runs can resume confirmed batches.

Initial Pinecone indexing embeds approximately total transcript tokens plus overlap
and one short completion-marker document;
subsequent unchanged indexing makes no embedding calls. Each question adds one
Pinecone-hosted query embedding plus one bounded-context OpenAI chat generation, unless retrieval
finds no qualifying evidence. OpenAI/Pinecone usage may be billable depending on
your accounts. Budget from token counts and provider rates rather than assuming
free requests. Normal tests use mocks and require no real credentials. No bulk
live indexing is performed without explicit authorization.

Conversation IDs/history remain bounded process memory (256 conversations, 20
recent turns), not durable or shared across Vercel instances. History is not sent
to the model: this milestone implements independent single-question RAG, not
persistent conversational memory. LangSmith tracing is disabled for RAG operations;
application progress logs include only video IDs/counts and safe error types.

For Vercel, add the same OpenAI/Pinecone settings above, existing Supabase keys,
`APP_ENV=production`, `TRANSCRIPT_SOURCE=supabase`, and exact frontend CORS origins.
Use identical chunk/embedding settings to local indexing. The deployed frontend's
`VITE_API_BASE_URL` points to the deployed FastAPI origin; keys remain backend-only.
The health endpoint keeps its legacy response fields for compatibility; its
`mode: "mock"` does not describe the now-real chat endpoint. Deployment is manual.

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
process request; chat requires an indexed transcript and returns `mode: "real"`
with validated retrieved sources.
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
Video processing, including reading its response body, times out after 180 seconds
to allow extraction, saving, and indexing. Connectivity checks retain a
15-second health timeout and 90-second chat timeout. Failures display an error
and release the button.

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
saved/indexed ID, a question, and null conversation ID; expect a real grounded answer.

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
conversation memory is not implemented; real single-question RAG is implemented.

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

Next: evaluate retrieval quality and add durable conversational memory and voice.
No agents, new database, or automatic deployment are introduced.
