# tubeInsight-ai backend

Rayhan builds the Python/FastAPI backend; Anita Kiran owns React. This README
reproduces backend **0.6.1**. No frontend changes are needed for stabilization.
The API serves original YouTube transcripts, video-bound tools and persistent
chat, plus a backend-only recorded-question transcription endpoint.

## Actual stack and architecture

Python 3.11+ (verified on 3.12), FastAPI/Pydantic, youtube-transcript-api, official
Supabase SDK/PostgreSQL, Pinecone, LangChain native StructuredTools/ChatOpenAI,
OpenAI chat/transcription, optional LangSmith and pytest. LangGraph is not used.
The existing `tubechunks` document index uses **Pinecone-hosted
llama-text-embed-v2, 1024 dimensions, cosine, chunk_text**. OpenAI handles chat and
speech; it does not supply embeddings for this user-selected index.

[Architecture and Mermaid flow](../docs/architecture.md) ·
[Agent tools](../docs/agent-tools.md) · [Conversation memory](../docs/conversation-memory.md) ·
[Evaluation evidence](../docs/evaluation-results.md) · [API contract](../docs/api-contract.md) ·
[Day 5 audit and changes](../docs/day5-implementation.md).

```text
backend/
  app/main.py              FastAPI, CORS and stable error mapping
  app/routers/             health, videos, chat, audio
  app/schemas/             existing public models and internal stored video
  app/services/            transcript ingestion, processing, chat, audio
  app/db/                  bounded official Supabase transport
  app/repositories/        video, memory and summary persistence
  app/rag/                 spans/chunks, versioned indexing, verified retrieval
  app/agent/               native tools, context, budgets, summaries, evidence, traces
  app/evaluation/          guarded offline/live CLI, scoring, reports, optional judge/export
  app/scripts/             explicit local ingestion/index/summary CLIs
  migrations/              001 videos; 002 memory and summaries
  evaluation/              reviewed synthetic fixtures and unreviewed real templates
  tests/                   no-cloud default regressions
  reports/evaluation/      generated ignored JSON/Markdown/CSV
```

## Local setup (PowerShell)

From the repository root:

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Create/copy these only for a fresh setup; preserve an existing venv and private
.env. Edit .env locally, never paste credentials into chat or commit them. If
activation is restricted, invoke `.\.venv\Scripts\python.exe` directly.
`load_dotenv` preserves inherited process variables, so restart the backend after
key changes and remove stale shell overrides when appropriate.

Apply all of migrations 001 then 002 in the matching Supabase project's SQL Editor
as project owner. The backend service key performs data operations, not arbitrary
schema administration. Existing projects with both migrations need **no Day 5
migration**. No index is created/deleted automatically: use the existing compatible
`tubechunks`. Install pinned dependencies without speculative provider upgrades.

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

[Swagger](http://localhost:8000/docs) · [OpenAPI](http://localhost:8000/openapi.json).
The OpenAPI version should be 0.6.1. Health is connectivity-only and preserves its
legacy service/mode strings; it is not a live database/model readiness test.

## Backend environment

The full commented template is [.env.example](.env.example). Keys stay server-side;
never use VITE_ for these values.

| Variable/group | Purpose/default |
| --- | --- |
| SUPABASE_URL, SUPABASE_SECRET_KEY | HTTPS project origin (no REST path) and current sb_secret_ backend key. |
| APP_ENV, TRANSCRIPT_SOURCE | Local development/auto; production/supabase. Vercel indicators always force cache-only. |
| CORS_ORIGINS | Exact comma-separated frontend origins; defaults localhost:5173/3000, never wildcard production. |
| OPENAI_API_KEY, OPENAI_CHAT_MODEL | Chat/speech key; configured chat default gpt-6-luna. No automatic model substitution. |
| PINECONE_API_KEY, PINECONE_INDEX_NAME | Existing compatible document index; tubechunks. |
| PINECONE_EMBEDDING_MODEL/FIELD/DIMENSIONS | llama-text-embed-v2 / chunk_text / 1024. Must match index schema/cosine. |
| OPENAI_TRANSCRIPTION_MODEL | gpt-transcribe. |
| MAX_AUDIO_UPLOAD_MB, AUDIO_TIMEOUT_SECONDS | Decimal file MB, default 4 (0.01–4 allowed); provider timeout 20s (1–30), no retries. |
| LANGSMITH_TRACING/KEY/PROJECT | Optional false/empty/tubeInsight-ai; safe content-free traces only. |
| EVALUATION_ENABLE_LIVE | false; live CLI also requires --enable-live. Keep false on Vercel. |
| EVALUATION_OUTPUT_DIR | reports/evaluation, ignored generated results. |

Validated resource controls:

| Controls | Defaults and meaning |
| --- | --- |
| SUPABASE_TIMEOUT_SECONDS | 10s, maximum 30; connect at most 3s, no SDK retries. |
| YOUTUBE_CAPTION_LANGUAGES / FALLBACK | en / true; original caption track priority and fallback, no translation. |
| YOUTUBE_CONNECT/READ/REQUEST_BUDGET_SECONDS | 3 / 10 / 30; at most six sends/three redirects, no retries or environment proxies. |
| RAG_CHUNK_SIZE / OVERLAP | 1000 / 180 characters; exact caption provenance. |
| RAG_EMBED_BATCH_SIZE / MAX_CHUNKS | 32 / 2000; local indexing bounds. |
| RAG_TOP_K / MIN_SCORE | 4 / 0.25; raw cosine retrieval gate, not calibrated semantic confidence. |
| RAG_API_TIMEOUT_SECONDS / INDEX_TIMEOUT_SECONDS | 10 / 90; bounded provider sockets / local batch deadline. |
| CHAT_HISTORY_MESSAGES / CHARS | 12 / 12000; bounded recent model context, not deletion of older rows. |
| AGENT_MAX_TOOL_CALLS / MAX_MODEL_CALLS | 3 / 6; unique executions cached within a request; native selection count remains bounded. |
| AGENT_REQUEST_BUDGET_SECONDS | 45; checked between bounded operations, not a hard process kill. |
| TRANSCRIPT_MAX_WINDOW_SECONDS / POINT_WINDOW_SECONDS | 600 / 30; time-range limit / centered point lookup. |
| TOOL_MAX_TEXT_CHARS | 14000 per tool result. |
| SUMMARY_BATCH_CHARS / MAX_BATCHES | 8000 / 3; complete selected material or controlled SUMMARY_TOO_LONG. |

See .env.example for exact full variable names. Existing provider/agent retries
remain as implemented: the active Day 3+ agent has no model retries. The legacy
Day 2 single-answer helper retains its older one-retry configuration and is not
the `/api/chat/ask` execution path.

## API requests and responses

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /api/health | Legacy connectivity envelope. |
| POST | /api/videos/process | Validate URL, prepare/read original captions. |
| POST | /api/chat/ask | Grounded tool-based answer with persistent session. |
| POST | /api/audio/transcribe | Short multipart audio to original-language text. |

All errors keep `{"error":{"code":"CODE","message":"Safe explanation"}}`.
No public evaluation, conversation-history/list, refresh or transcript-write route
exists. Missing/invalid request fields return 422 without echoing raw input.

Video request:

```json
{"url":"https://www.youtube.com/watch?v=VIDEO_ID_11"}
```

Response shape (illustrative placeholders, not a measured transcript):

```json
{"status":"ready","mode":"real","video":{"id":"VIDEO_ID_11","title":null,"url":"https://www.youtube.com/watch?v=VIDEO_ID_11","thumbnail_url":"https://img.youtube.com/vi/VIDEO_ID_11/hqdefault.jpg","duration_seconds":null},"transcript":[{"start_seconds":0.0,"end_seconds":4.0,"text":"Actual caption returned by the provider."}]}
```

Chat request:

```json
{"video_id":"VIDEO_ID_11","question":"What are the three main topics?","conversation_id":null}
```

Response shape:

```json
{"video_id":"VIDEO_ID_11","conversation_id":"00000000-0000-4000-8000-000000000001","mode":"real","answer":"Answer grounded in selected video evidence.","sources":[{"start_seconds":30.0,"end_seconds":55.0,"text":"Actual supporting transcript excerpt."}]}
```

Replace placeholders with a real cached video and returned session UUID. A
follow-up reuses that UUID: `Explain the second one.` New null-ID requests start
independently. Unknown/cross-video IDs return 404; busy sessions return 409.
Unresolved ordinal searches can return 422 FOLLOWUP_CONTEXT_REQUIRED asking the
client to name the topic; no new frontend request/response fields are introduced.

### Audio and Postman

POST http://localhost:8000/api/audio/transcribe. Choose Body → form-data → key
`file`, change Text to File, select a short recording. Let Postman set Content-Type
with its boundary; do not manually select JSON. Swagger also has a file picker.

```powershell
curl.exe -X POST http://localhost:8000/api/audio/transcribe -F "file=@C:/recordings/question.webm"
```

```json
{"text":"What are the main topics?","language":null,"model":"gpt-transcribe"}
```

Language is populated only for a reliable single provider language. This uses
transcription, not translation; submit the returned text separately through chat.
Anita's frontend microphone UI may still be pending and is not implemented here.

MP3/MP4/MPEG/MPGA/M4A/PCM WAV/WebM Opus/Vorbis receive practical content checks,
not merely filename/MIME checks; OpenAI performs deep decoding. PCM silence is
rejected locally, while compressed silence/noise depends on the provider. File
limit is 4,000,000 bytes plus at most 64,000 multipart bytes; upload reception is
bounded to 15s. Temporary UploadFile spools/buffers close without permanent audio
storage. No audio is saved to Supabase/Pinecone/LangSmith. No FFmpeg or local
Whisper dependencies exist. ASR may be wrong; users should review question text.

Audio errors: 400 AUDIO_EMPTY; 408 AUDIO_UPLOAD_TIMEOUT; 413 AUDIO_TOO_LARGE;
415 AUDIO_UNSUPPORTED_FORMAT; 422 AUDIO_INVALID/AUDIO_NO_SPEECH/VALIDATION_ERROR;
429 AUDIO_RATE_LIMITED; 500 CONFIGURATION_ERROR; 502 AUDIO_TRANSCRIPTION_FAILED;
503 AUDIO_UNAVAILABLE; 504 AUDIO_TIMEOUT. Provider bodies, file contents and
credentials are not exposed in errors. Socket timeouts are not a hard kill deadline.

## Transcript caching and indexing

Local auto mode: Supabase read → direct YouTube on miss → validate/confirm save →
local idempotent indexing. Cache hits skip YouTube and ready manifests skip video
re-embedding. Failed extraction does not overwrite valid cache. Production/preview
read only cached captions and existing vectors, even if auto was misconfigured.

Explicit local tools, only when you intend to contact real providers:

```powershell
python -m app.scripts.ingest_video "https://www.youtube.com/watch?v=VIDEO_ID_11"
python -m app.scripts.index_cached_videos --video-id VIDEO_ID_11
python -m app.scripts.precompute_summary --video-id VIDEO_ID_11 --detail brief
```

`--force` exists on ingestion/indexing and can incur rework/embedding charges; it
is not automatic. Batch ingestion/indexing is explicit CLI work. Stable chunk IDs,
fingerprinted namespaces, verified batches and a completion manifest support
resume and avoid cross-video/stale-source retrieval. Old namespaces are retained.
Do not run full indexing or long summary precomputation inside Vercel requests.

Search checks original chunk text, video/fingerprint metadata and timestamps;
float32 storage rounding never replaces exact original response timestamps.
Time lookup uses chronological overlapping original captions and half-open bounds.
Full/interval summaries cover all selected chunks or fail safely before oversized
work, and cache canonical results in Supabase. Equivalent tool calls execute once
per request, with valid native replies for every call ID. Provenance does not prove
semantic support; reviewed references/human or optional judge review are required.

## Conversation memory and tracing

Supabase chat_sessions/chat_messages use leases plus token/revision checks and
an atomic two-message exchange RPC. History is chronological and bounded; fresh
sessions are isolated and cross-video UUID reuse is rejected. Failure cleanup is
best-effort and leases expire. See the memory document for acknowledgement/retry
and lease-clock limits. **UUIDs are sensitive identifiers, not authenticated user
ownership.** There is no history-list endpoint or ownership/auth system yet.

LANGSMITH_TRACING=true plus a private key enables existing restricted spans.
Inputs/outputs, history, transcript text and audio are hidden; safe operation,
video/environment/token counts and monotonic durations may be exported. Optional
failures do not break the app. Default CLI offline mode disables all uploads.
Logs/reports must never contain keys, auth headers, proxy URLs or conversation IDs.
Redaction is best-effort for recognizable secrets, not universal PII removal.

## Tests and evaluation

```powershell
python -m pytest -q
python -m pip check
python -m app.evaluation.run --mode offline
```

Default tests mock external services and block unexpected network sends; no real
keys are needed. The offline CLI exercises actual services/tools with scripted
providers and synthetic captions. Windows internal loopback event-loop sockets
are allowed, external services are blocked. Reports are ignored timestamped JSON,
Markdown and CSV. There is no configured formatter/linter/type checker to install
or upgrade; pytest, dependency consistency, compilation and diff checks are used.

[Evaluation schema, curation and human rubric](evaluation/README.md). The 18
synthetic cases cover facts, unsupported questions, time intervals/out-of-range,
summaries, memory, tools and six audio outcomes. Offline ASR is mocked, so WER is
null. Mechanical pass/fail and phrase diagnostics do not prove real AI quality.
Real templates in `curated.json` are unreviewed: manually replace questions,
reference facts/ranges/tools, read the full cached transcript and pin its SHA256.
Keep private references/recordings in ignored private* locations. Reports omit raw
questions, answers, sources, audio and conversation UUIDs.

Only after curation and explicit willingness to incur charges/transfer data:

```powershell
$env:EVALUATION_ENABLE_LIVE = 'true'
python -m app.evaluation.run --mode live --enable-live --dataset curated --max-examples 3 --max-model-calls 12
Remove-Item Env:EVALUATION_ENABLE_LIVE
```

Live mode requires both guards, prints a warning, is sequential, allows at most
five cases/three turns each and 30 OpenAI call reservations (default 12). Existing
per-request limits remain. Audio and optional `--judge` share that cap; Pinecone
query embeddings are additional bounded provider work. No extraction/indexing
runs. Normal test conversations and summaries persist in Supabase. A reviewed
real-level audio dataset can measure actual WER, with the same explicit guards.

Optional `--judge` applies the explicit fallible semantic rubric to verified sources.
Optional `--upload-langsmith --experiment-name tubeinsight-demo` creates a named
case-ID-only dataset and replays sanitized measured results as an experiment,
without another model run. Inputs/outputs remain hidden; explicit feedback carries
scores and original duration. LangSmith replay durations are export overhead; use
measured_duration_seconds feedback/local spans for app latency. No raw content or
audio is uploaded. Both features are live-only and disabled by default.

The two legacy integration tests require RUN_YOUTUBE_INTEGRATION or
RUN_SUPABASE_INTEGRATION and appropriate configured providers; the Supabase test
may ingest if missing. They are skipped by default and were not enabled in Day 5.
Do not confuse those with paid RAG/audio semantic evaluations or human review.

## Manual Vercel deployment and verification

No commit, push or deployment is performed automatically. The current repo has no
checked-in Vercel configuration to audit; existing dashboard settings are not
inspected. Preserve the working project/entrypoint. For a backend-only project,
use backend as Root Directory and FastAPI preset/entry app/main.py exporting app;
verify this against the current [Vercel FastAPI guide](https://vercel.com/kb/guide/ship-a-fastapi-app-on-vercel).
Do not modify Anita's frontend project to deploy this backend.

1. Review the diff and run tests/offline evaluation. Curate at least one public
   cached/indexed demo video locally, only with explicit provider-call authorization.
2. Verify migrations 001/002 in the intended Supabase project. Day 5 adds no SQL.
3. In backend project Settings → Environment Variables, set private Supabase,
   OpenAI and Pinecone credentials; preserve the matching Llama index settings.
   Set APP_ENV=production, TRANSCRIPT_SOURCE=supabase, exact CORS_ORIGINS,
   OPENAI_CHAT_MODEL=gpt-6-luna, OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe,
   MAX_AUDIO_UPLOAD_MB=4, AUDIO_TIMEOUT_SECONDS=20, EVALUATION_ENABLE_LIVE=false.
   Tracing stays optional. Never copy secrets into frontend variables.
4. Choose the intended Preview/Production environment and supported Python runtime
   (local verification used 3.12). Keep existing build/entrypoint settings unless
   a verified deployment error requires correction. Dependency pins are unchanged.
5. After you choose to publish the reviewed code to the configured Git source,
   deploy the intended revision through the existing Vercel project's workflow.
   Environment edits require a new deployment. First verify a preview if available,
   then promote the reviewed successful revision manually.
6. GET deployed /openapi.json (0.6.1/four routes) and /api/health. Process the known
   cached URL; expect real stored captions. An uncached URL should fail with
   TRANSCRIPT_NOT_CACHED, without contacting YouTube. Verify a disallowed CORS origin.
7. Only when you intend paid calls, ask one reviewed factual question, one absent
   fact and a same-ID follow-up; compare source text/times with original captions.
   Upload one short recording in Postman, review text, then submit through chat.
   These live/semantic checks have **not** been performed by Day 5 automation.
8. Observe safe errors/traces and provider usage. Revert to a known revision through
   Vercel if verification fails; do not delete original transcripts/indexes.

[Vercel's request payload ceiling](https://vercel.com/docs/functions/limitations)
is 4.5 MB. Platform rejection may precede the app and use its own error envelope.
Keep large indexing and summaries local; no paid proxy or background promise is
required. Long recordings need a future separate upload/storage workflow.

## Remaining limitations

Real-video semantic accuracy, live ASR and production latency are **Not yet
measured** by this stabilization run. Historical Day 3 live checks do not replace
new measurements. Small-sample p95 and mocked timings are labeled explicitly.
Native tool choice/general-language reference resolution remains model-dependent;
numbered follow-up support is conservative. Raw retrieval thresholds need real
calibration. Caption overlap retains full original text, not time-clipped phrases.

The current API lacks authenticated ownership and durable paid-request quotas.
Before broad public exposure, add an authorization/gateway strategy, per-user/IP
quotas, concurrency protection and provider spend caps/alerts. CORS and an in-memory
limiter cannot enforce distributed access/quotas. No such new system is introduced
here. Summary semantic coverage, provider recognition and model claims require
review; original-source checks alone are insufficient. See the linked audit and
evaluation reports for actual evidence and unresolved measurement work.
