# VideoWise AI mock backend

Python 3.11+ and FastAPI. This Day 1 API returns simulated video metadata,
transcripts, and answers for React integration. It never calls YouTube, an LLM,
a database, or a transcription service.

## Setup and start

From the repository root, in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The `.env` copy is optional; the development defaults work without it. If you
already have a local `.env`, keep it and edit its values as needed.

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python` instead of
`.\.venv\Scripts\python.exe`, and `cp .env.example .env` to copy the example.
Virtual environment activation is optional with these commands.

- Base URL: <http://localhost:8000>
- Swagger: <http://localhost:8000/docs>
- OpenAPI schema: <http://localhost:8000/openapi.json>
- Frontend contract: [api-contract.md](../docs/api-contract.md)
- Copyable TypeScript interfaces: [api-types.ts](../docs/api-types.ts)

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Check connectivity and mock mode |
| POST | `/api/videos/process` | Validate a YouTube URL and return simulated data |
| POST | `/api/chat/ask` | Return a fixed simulated answer and timestamped sources |

## Configuration

`CORS_ORIGINS` is a comma-separated list of exact frontend origins. Defaults:

```dotenv
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

The backend loads `backend/.env` independently of the working directory.
Environment variables set in the shell take precedence. Restart the backend
after configuration changes. Wildcards and origins containing paths are rejected
at startup. Production must supply its own explicit allowed origins. Setting
`CORS_ORIGINS` to an empty string disables cross-origin access.

## Tests

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use FastAPI's TestClient with isolated in-memory state and no external
requests. They cover the three URL formats, malicious/malformed URLs, response
contracts, validation, conversation creation/reuse/video binding, history,
unexpected errors, CORS, and Swagger/OpenAPI.

## Try it

Run these in Bash, or in PowerShell 7.3+ using `curl.exe` instead of `curl`:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/videos/process -H 'Content-Type: application/json' -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
curl -X POST http://localhost:8000/api/chat/ask -H 'Content-Type: application/json' -d '{"video_id":"dQw4w9WgXcQ","question":"What is this video about?","conversation_id":null}'
```

Windows PowerShell 5.1 has different native JSON argument quoting. These native
PowerShell commands work there as well:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/videos/process -Method Post -ContentType 'application/json' -Body '{"url":"https://youtu.be/dQw4w9WgXcQ"}'
Invoke-RestMethod http://localhost:8000/api/chat/ask -Method Post -ContentType 'application/json' -Body '{"video_id":"dQw4w9WgXcQ","question":"What is this video about?","conversation_id":null}'
```

Process the video before asking a question. For a follow-up, send the returned
`conversation_id` with the same `video_id`. See the contract for full payloads,
error examples, and the React workflow.

## Dependencies

- FastAPI: HTTP routing, validation, and Swagger/OpenAPI.
- Uvicorn: development ASGI server.
- Pydantic v2: reusable request and response schemas.
- python-dotenv: optional local `.env` configuration.
- pytest and httpx: automated TestClient tests.

Version ranges are in `requirements.txt`. No AI or YouTube extraction packages
are required.

## Scope and storage

`app/routers/` handles HTTP; `app/schemas/` defines public models;
`app/services/` owns the mock behavior. Future integrations should replace the
service implementations while retaining response field names, nullable metadata,
numeric second timestamps, and the shared error envelope. The current mode is
`mock`; coordinate any future mode values with the frontend contract and types.

Processed videos and conversation histories live in Python dictionaries. They
reset when the backend process restarts, including automatic development reloads.
They are not shared between workers and are unsuitable for multiple production
workers. Run one worker for this mock. History is retained for the process
lifetime; this prototype has no persistence or retention policy. Storing history
does not affect the fixed answer, and the sources refer only to simulated text.
