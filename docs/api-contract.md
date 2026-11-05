# tubeInsight-ai â€” Phase 2 API contract

The backend checks Supabase first. Local `TRANSCRIPT_SOURCE=auto` automatically
fetches and saves missing real captions before returning success.
Vercel HTTP requests never contact YouTube. React request bodies and success
response field names/types remain unchanged; chat answers remain mocked.

## Connection and endpoints

- Base URL: `http://localhost:8000`
- [Swagger](http://localhost:8000/docs), [OpenAPI](http://localhost:8000/openapi.json)
- JSON requests use `Content-Type: application/json`. No Supabase key goes to React.
- Default CORS origins: `http://localhost:5173`, `http://localhost:3000`.
- [Setup and ingestion](../backend/README.md), [TypeScript types](api-types.ts).

| Method | Path | Success |
| --- | --- | --- |
| GET | `/api/health` | 200: existing connectivity response |
| POST | `/api/videos/process` | 200: saved real transcript |
| POST | `/api/chat/ask` | 200: fixed mock answer |

There is no public ingestion, refresh, or transcript-write route.

## GET `/api/health`

No request body. HTTP 200:

```json
{"status":"ok","service":"videowise-api","mode":"mock"}
```

The legacy identifier/mode remain for compatibility. This checks connectivity,
not Supabase readiness. Product name: tubeInsight-ai. Video/chat declare their
own modes separately.

## POST `/api/videos/process`

Request:

```json
{"url":"https://www.youtube.com/watch?v=Gfr50f6ZBvo"}
```

`url` is a required string. Supported forms remain watch URLs, `https://youtu.be/ID`,
and `https://www.youtube.com/shorts/ID`. Exact case-insensitive hosts: `youtube.com`,
`www.youtube.com`, `m.youtube.com`, `youtu.be`, `www.youtu.be`. HTTP/HTTPS are accepted.
Short links/Shorts may have a trailing slash. Extra parameters/fragments do not
change the ID; watch URLs need exactly one `v`. IDs have exactly 11 ASCII letters,
digits, `_`, or `-`. Credentials, explicit ports, whitespace/control characters,
lookalike domains, unsupported paths, or malformed IDs return 400. Missing/non-string
fields return 422.

The backend validates the URL and looks up its ID in Supabase. HTTP 200 structure
(the caption text/timestamps below are illustrative, not this video's actual data):

```json
{
  "status": "ready",
  "mode": "real",
  "video": {
    "id": "Gfr50f6ZBvo",
    "title": null,
    "url": "https://www.youtube.com/watch?v=Gfr50f6ZBvo",
    "thumbnail_url": "https://img.youtube.com/vi/Gfr50f6ZBvo/hqdefault.jpg",
    "duration_seconds": null
  },
  "transcript": [
    {
      "start_seconds": 0.0,
      "end_seconds": 4.5,
      "text": "Illustrative caption; actual responses contain saved original text."
    }
  ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | string, `"ready"` | Valid saved transcript is available |
| `mode` | string, `"real"` | Genuine saved captions; does not imply real AI chat |
| `video.id` | string | Actual 11-character ID; use as chat `video_id` |
| `video.title` | string or null | Saved title if known; normally null |
| `video.url` | string | Canonical YouTube watch URL |
| `video.thumbnail_url` | string | Saved thumbnail or existing ID-based fallback |
| `video.duration_seconds` | integer or null | Nonnegative saved duration if known |
| `transcript` | array of segments | Nonempty saved captions in original order |

Every field stays present, including nullable metadata. Ingestion never invents
metadata, text, or timestamps. Caption language is saved internally without adding
a response field. Repeated requests read persistent data, with no in-memory video
dependency, processing job, or polling route.

In cache-only mode (`TRANSCRIPT_SOURCE=supabase`, any Vercel deployment, or
`APP_ENV=production`), a valid but unprepared video returns HTTP 404:

```json
{
  "error": {
    "code": "TRANSCRIPT_NOT_CACHED",
    "message": "This video has not been prepared yet."
  }
}
```

This is expected. Retrying processing cannot ingest the video: a developer must
run the local CLI first. No failure returns fake caption data or triggers YouTube.

## Transcript and source segments

| Field | Type | Meaning |
| --- | --- | --- |
| `start_seconds` | number | Nonnegative seconds from video start |
| `end_seconds` | number | Actual caption start plus duration |
| `text` | string | Original plain caption text |

All fields are required. Fractional seconds, ordering, gaps, and overlaps are
preserved. Format `m:ss` only for labels; keep numeric seconds for seeking.
The local provider prefers English by default and can fall back to another
original language. It never translates silently.

## POST `/api/chat/ask`

A video must exist in Supabase. A previous process request is not required.

```json
{
  "video_id": "Gfr50f6ZBvo",
  "question": "What is this video about?",
  "conversation_id": null
}
```

| Field | Type | Required? | Rules |
| --- | --- | --- | --- |
| `video_id` | string | Yes | Valid 11-character saved ID |
| `question` | string | Yes | Trimmed and nonblank |
| `conversation_id` | UUID string or null | No | Null/omitted starts; reuse returned ID for follow-ups |

HTTP 200 (UUID/source excerpt are illustrative):

```json
{
  "video_id": "Gfr50f6ZBvo",
  "conversation_id": "e06a3f5a-1ad0-4e89-9f2b-172ed725fdc1",
  "mode": "mock",
  "answer": "This is a simulated AI response for frontend development. Real answers will be generated from the video transcript in a future version.",
  "sources": [
    {
      "start_seconds": 0.0,
      "end_seconds": 4.5,
      "text": "Illustrative caption; actual responses contain saved original text."
    }
  ]
}
```

All fields are present. IDs, mode, and answer are strings; sources is an array
of segments. New conversation IDs are UUID v4 and stay tied to one video.
History is retained locally, but does not affect the fixed answer. Its source is
the first saved caption for citation UI testing, not evidence supporting a real
answer. Keep the mock-answer notice.

Unknown saved IDs return `VIDEO_NOT_FOUND` (404). Unknown/expired conversations
or a different video return `CONVERSATION_NOT_FOUND` (404). Video lookup happens
first. Conversation state is still in process memory: another Vercel instance can
reject a previous UUID even though the saved video remains available. Start a
new chat with null after that error.

## Error envelope

All errors retain `error.code` and `error.message`. Use codes for behavior;
message wording may vary.

| HTTP | Code | Situation |
| --- | --- | --- |
| 400 | `INVALID_YOUTUBE_URL` | Unsupported/malformed URL or ID |
| 404 | `TRANSCRIPT_NOT_CACHED` | Processing an unprepared video |
| 404 | `VIDEO_NOT_FOUND` | Chat video not saved |
| 404 | `CONVERSATION_NOT_FOUND` | Unknown/expired UUID or wrong video |
| 422 | `VALIDATION_ERROR` | Missing/invalid fields or malformed JSON |
| 500 | `CONFIGURATION_ERROR` | Missing/invalid backend settings |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected failure |
| 502 | `INVALID_STORED_TRANSCRIPT` | Corrupt captions; locally reingest with `--force` |
| 503 | `DATABASE_UNAVAILABLE` | Supabase network/auth/permission/schema failure |

```json
{"error":{"code":"VALIDATION_ERROR","message":"Missing or invalid request fields: body.question."}}
{"error":{"code":"DATABASE_UNAVAILABLE","message":"Transcript storage is unavailable. Try again later."}}
{"error":{"code":"CONFIGURATION_ERROR","message":"Configure SUPABASE_URL and SUPABASE_SECRET_KEY on the backend."}}
```

Processing documents 400/403/404/422/429/500/502/503/504; chat
404/422/500/502/503; health 500.
Routing errors retain `NOT_FOUND` (404) and `METHOD_NOT_ALLOWED` (405). CORS
preflight uses middleware. Database failures do not become cache misses. YouTube
errors belong to local auto processing and ingestion, not the deployed API. Keys and raw
upstream exceptions are never returned.

## React and deployment

Anita needs no request, success-model, component, or environment changes if the
backend base URL remains the same. Continue to:

1. Use separate video/chat loading flags, disable duplicates, clear loading in
   `finally`, and check `response.ok` before consuming success JSON.
2. Display readable input/API errors. On `TRANSCRIPT_NOT_CACHED`, explain that
   preparation is required; do not loop processing requests.
3. Store returned video/transcript, use `video.id` for chat, reset conversations
   on video changes, and ignore/abort stale responses.
4. Render thumbnails with a failure fallback, nullable title/duration sensibly,
   and captions in order with React escaping.
5. Use numeric timestamps for existing YouTube links (`&t=SECONDSs`, flooring the
   start seconds). An initialized IFrame Player API can use `seekTo(seconds, true)`;
   an ordinary iframe DOM element cannot.
6. Reuse the chat UUID on the same video; clear it on `CONVERSATION_NOT_FOUND`.

Vercel needs backend-only `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
`APP_ENV=production`, `TRANSCRIPT_SOURCE=supabase`, and explicit frontend
`CORS_ORIGINS`. Optional
`SUPABASE_TIMEOUT_SECONDS` defaults to 10. No Supabase secret belongs in React or
API requests. Follow the README to migrate, ingest locally, redeploy manually,
and verify in Postman/React. Arbitrary unprepared videos and real RAG answers are
outside this phase.
