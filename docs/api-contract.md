# tubeInsight-ai — Phase 1 API contract

Video processing now returns actual available YouTube captions. Chat still
returns a fixed simulated answer. No AI answer is grounded in the transcript yet.
The field names and request bodies used by React are unchanged.

## Connection and endpoints

- Base URL: `http://localhost:8000`
- Swagger: <http://localhost:8000/docs>
- OpenAPI: <http://localhost:8000/openapi.json>
- Send JSON with `Content-Type: application/json`; no authentication is required.
- Development origins: `http://localhost:5173` and `http://localhost:3000`.
- Other origins require backend `CORS_ORIGINS` configuration.
- [Backend setup/configuration](../backend/README.md), [shared TypeScript types](api-types.ts).

| Method | Path | Success |
| --- | --- | --- |
| GET | `/api/health` | 200: existing connectivity response |
| POST | `/api/videos/process` | 200: real transcript, `status: "ready"`, `mode: "real"` |
| POST | `/api/chat/ask` | 200: fixed answer, `mode: "mock"` |

## GET `/api/health`

No request body. Its legacy service identifier and mode are retained for existing
consumers; video and chat responses declare their respective modes separately.

```json
{"status":"ok","service":"videowise-api","mode":"mock"}
```

All three fields are required strings. The product name is tubeInsight-ai;
health's legacy identifier is preserved solely for compatibility.

## POST `/api/videos/process`

Request:

```json
{"url":"https://www.youtube.com/watch?v=Gfr50f6ZBvo"}
```

`url` is required and must be a string. Supported examples:

- `https://www.youtube.com/watch?v=Gfr50f6ZBvo`
- `https://youtu.be/Gfr50f6ZBvo`
- `https://www.youtube.com/shorts/Gfr50f6ZBvo`

The existing validator allows HTTP/HTTPS and exact hosts `youtube.com`,
`www.youtube.com`, `m.youtube.com`, `youtu.be`, and `www.youtu.be`, case insensitive.
Short links/Shorts may end with a slash. Extra query parameters and fragments do
not change the extracted ID; watch URLs must contain exactly one `v` parameter.
Embedded-player URLs, credentials, explicit ports, whitespace/control characters,
lookalike domains, missing IDs, and IDs other than 11 ASCII letters/digits/`_`/`-`
are rejected with 400. Missing/non-string URL fields return 422.

HTTP 200 structure (illustrative caption text/timestamps, not an assertion about
this video's contents):

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
      "text": "An illustrative caption; actual responses contain retrieved text."
    }
  ]
}
```

| Response field | Type | Meaning |
| --- | --- | --- |
| `status` | string, `"ready"` | Real caption extraction succeeded |
| `mode` | string, `"real"` | Real video transcript; does not imply real AI chat |
| `video.id` | string | Actual extracted 11-character ID; use this as chat `video_id` |
| `video.title` | string or null | Currently null; render a fallback |
| `video.url` | string | Canonical `https://www.youtube.com/watch?v=ID` |
| `video.thumbnail_url` | string | Existing YouTube thumbnail pattern |
| `video.duration_seconds` | integer or null | Currently null; hide unknown duration |
| `transcript` | array of segments | Nonempty actual caption segments in provider order |

Every field above is present. Nullable fields are not omitted. Caption languages
are selected using backend `YOUTUBE_CAPTION_LANGUAGES` (default `en`), preferring
manual over automatic within the preferred language. English automatic captions
outrank a manual non-English track. Regional English is supported. With
`YOUTUBE_CAPTION_FALLBACK=true`, another available original language may be used.
No translation occurs; the response text remains in the selected track's language.
No new language metadata field is introduced in this phase.

Only successful extraction returns 200/`ready`. Captions disabled, absent, empty,
restricted, or blocked are errors; the backend never substitutes mock segments.
Title/duration retrieval is not required for transcript success. Reprocessing a
video retains its ID and does not deliberately erase conversations in that process.

## Transcript and source segment structure

| Field | Type | Meaning |
| --- | --- | --- |
| `start_seconds` | number | Nonnegative seconds from video start |
| `end_seconds` | number | Caption start plus its actual duration |
| `text` | string | Original plain caption text returned by the provider |

All segment fields are required. Timestamps can be fractional; they are seconds,
not milliseconds or formatted strings. Gaps and overlapping segments are
preserved. Do not assume a segment ends exactly where the next one starts.

## POST `/api/chat/ask`

Process the video first. Request:

```json
{
  "video_id": "Gfr50f6ZBvo",
  "question": "What is this video about?",
  "conversation_id": null
}
```

| Request field | Type | Required? | Rules |
| --- | --- | --- | --- |
| `video_id` | string | Yes | Valid 11-character ID returned as `video.id` |
| `question` | string | Yes | Trimmed; whitespace-only questions are rejected |
| `conversation_id` | UUID string or null | No | Omit/null for a new chat; reuse returned UUID for follow-ups |

HTTP 200 (UUID and source excerpt are illustrative):

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
      "text": "An illustrative caption; actual responses contain retrieved text."
    }
  ]
}
```

All response fields are required. `video_id`, `conversation_id`, `mode`, and
`answer` are strings; `sources` is an array with the segment structure above.
The backend generates a UUID v4 on the first request. Send the same `video_id`
and returned `conversation_id` for follow-ups. A conversation cannot change videos.
Minimal history is kept, but the answer does not depend on question/history.

Sources currently contain the first retrieved caption segment for frontend
citation testing. It is real text, but it is **not evidence supporting the mock
answer**. Keep a visible mock-answer notice. There is no LLM or RAG in this phase.

## Error envelope and codes

```json
{
  "error": {
    "code": "TRANSCRIPT_NOT_AVAILABLE",
    "message": "No transcript is available for this video."
  }
}
```

Read `error.code` for behavior and `error.message` for a readable explanation;
message wording is not a stable discriminator. Raw upstream errors are not exposed.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `INVALID_YOUTUBE_URL` | Invalid/malformed URL or ID |
| 403 | `VIDEO_UNAVAILABLE` | Private, restricted, or unplayable video |
| 404 | `VIDEO_UNAVAILABLE` | Removed/missing video |
| 404 | `TRANSCRIPT_NOT_AVAILABLE` | No usable captions or allowed caption language |
| 429 | `YOUTUBE_RATE_LIMITED` | YouTube returned 429; may also indicate an IP block |
| 502 | `TRANSCRIPT_FETCH_FAILED` | Upstream connection, parsing, or data failure |
| 503 | `YOUTUBE_ACCESS_BLOCKED` | Server requests blocked or required upstream token unavailable |
| 504 | `TRANSCRIPT_FETCH_TIMEOUT` | YouTube timed out or request budget exhausted |
| 404 | `VIDEO_NOT_FOUND` | Chat cannot find processed video in current process |
| 404 | `CONVERSATION_NOT_FOUND` | Unknown conversation or wrong video |
| 422 | `VALIDATION_ERROR` | Missing/invalid fields, blank question, invalid UUID, malformed JSON |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected backend error |

Additional examples:

```json
{"error":{"code":"INVALID_YOUTUBE_URL","message":"Please provide a valid YouTube URL."}}
{"error":{"code":"VIDEO_NOT_FOUND","message":"Process this video before asking questions."}}
{"error":{"code":"CONVERSATION_NOT_FOUND","message":"Conversation not found for this video."}}
{"error":{"code":"VALIDATION_ERROR","message":"Missing or invalid request fields: body.question."}}
{"error":{"code":"YOUTUBE_ACCESS_BLOCKED","message":"YouTube is blocking caption requests from this server."}}
{"error":{"code":"INTERNAL_SERVER_ERROR","message":"An unexpected backend error occurred."}}
```

The video endpoint documents 400/403/404/422/429/500/502/503/504. Chat retains
404/422/500; health documents 500. Unknown routes and unsupported methods use the
same envelope with `NOT_FOUND` (404) and `METHOD_NOT_ALLOWED` (405). Browser CORS
preflight failures are handled by middleware before an application response.

## React integration and seeking

1. Keep the same base URL configuration and `{url}`/chat request bodies. The
   frontend video response type now accepts `"mock" | "real"` for compatibility;
   chat still accepts `"mock"`. No API client or component redesign is needed.
2. Use separate video/chat loading flags, disable duplicate submissions, and
   clear loading in `finally`. Check `response.ok` before consuming success JSON.
   Display `error.message` near the relevant input; handle network failures that
   have no JSON response separately. Avoid automatic rapid retries on 429/503.
3. Store returned `video` and `transcript`; use `video.id` for chat. Reset the
   conversation when switching videos and ignore/abort stale responses.
4. Render `thumbnail_url` with alt text and an image-error fallback. Use a title
   fallback for null and hide unknown duration. Render original caption text using
   React escaping, in returned order, with formatted start timestamps.
5. Keep transcript timestamps numeric for seeking; format `m:ss` only for labels.
   The existing frontend links to `https://www.youtube.com/watch?v=ID&t=SECONDSs`
   using `Math.floor(segment.start_seconds)`. If embedding a player later, initialize
   the YouTube IFrame Player API and call `player.seekTo(start_seconds, true)`.
   Ordinary iframe DOM elements do not expose `seekTo`.
6. Retain the returned conversation UUID for follow-ups on that video. Chat
   answers remain labeled mock, even though their source segment contains real text.
7. On `VIDEO_NOT_FOUND`, process again. On `CONVERSATION_NOT_FOUND`, clear the
   conversation ID and start a new one. On 504/502 offer a user-controlled retry;
   on 404 captions unavailable, explain that another video may be needed.

## Deployment and persistence boundary

Caption fetching runs synchronously inside the existing route's worker thread,
with bounded connection/read timeouts and HTTP sends. There is no processing job
or polling endpoint. See the backend README for configuration and live testing.

Video and conversation dictionaries remain process-local. A Vercel cold start
or a different function instance can lose video/chat state immediately between
requests; warm-instance reuse is not guaranteed persistence. This phase reports
those failures honestly and does not recreate transcripts or conversations from
fake data. A shared persistent video/transcript/conversation store is required
before relying on chat across instances. Then RAG can index stored timestamped
chunks and return real answers with matching citations.

Local success does not verify Vercel access to YouTube: cloud IP blocking and
region-specific restrictions remain possible. No deployment, paid provider,
proxy credentials, or new persistent storage is introduced automatically.
