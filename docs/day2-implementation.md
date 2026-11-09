# tubeInsight-ai Day 2 implementation

The user selected the existing tubechunks document-schema index, using Pinecone's
llama-text-embed-v2 passage/query embeddings, chunk_text, 1024 dimensions, cosine.
This explicitly replaces the original OpenAI-embedding/1536-dimensional proposal.
OpenAI gpt-6-luna remains the real answer model. No index was created or deleted.

## Validation

- Backend: 267 passed, 2 opt-in live tests skipped; all normal external calls mocked.
- Frontend: 10 tests, production build, and lint passed.
- pip check: no broken requirements.
- Live: one cached video indexed into 3 chunks; unchanged repeat skipped embedding.
- Real /api/chat/ask returned mode=real, a grounded answer, and a verified source.
- Source text and exact timestamps were checked against the saved transcript plan.
- Unsupported question returned honest abstention and no sources.
- A different unindexed cached video returned VIDEO_NOT_INDEXED without leakage.
- Restarted localhost API 0.4.0: Process and real chat both returned HTTP 200;
  CORS matched localhost:5173, and Vite served the updated client/UI.
- Actual Vercel deployment and browser interaction are not claimed by these checks.

## Dependencies installed

langchain-core==1.7.6, langchain-openai==1.7.4,
langchain-pinecone==0.2.13, langchain-text-splitters==1.1.3,
openai==3.46.0, pinecone==7.3.0 (plus resolved transitive dependencies).
LangChain LCEL orchestrates prompts and native structured answers. The Pinecone
store extension uses the documented 2026-07 documents API because the integration
pins SDK <8, whose vector endpoints cannot read this existing document schema.

## Usage and limits

See ../backend/README.md for environment setup, local startup, one-video indexing,
explicit bulk backfill, Postman examples, React use, provider limits, cost factors,
and Vercel configuration. Conversation IDs are compatible but process-local;
there is no durable conversational memory, agent, or voice pipeline. Old vector
namespaces are retained; separate concurrent indexers can duplicate embedding
work. Providers can still rate limit or fail, and retrieval quality needs ongoing
evaluation. Credentials are never logged or copied into frontend configuration.

## Created or modified files

- `backend/.env` (private-settings)
- `backend/.env.example` (update)
- `backend/README.md` (update)
- `backend/app/main.py` (update)
- `backend/app/rag/__init__.py` (add)
- `backend/app/rag/answering.py` (add)
- `backend/app/rag/chunking.py` (add)
- `backend/app/rag/document_store.py` (add)
- `backend/app/rag/indexing.py` (add)
- `backend/app/rag/metadata.py` (add)
- `backend/app/rag/providers.py` (add)
- `backend/app/rag/settings.py` (add)
- `backend/app/repositories/video_repository.py` (update)
- `backend/app/routers/chat.py` (update)
- `backend/app/schemas/chat.py` (update)
- `backend/app/schemas/error.py` (update)
- `backend/app/scripts/index_cached_videos.py` (add)
- `backend/app/services/chat_service.py` (add)
- `backend/app/services/mock_chat_service.py` (update)
- `backend/app/services/video_service.py` (update)
- `backend/requirements.txt` (update)
- `backend/tests/conftest.py` (update)
- `backend/tests/test_api.py` (update)
- `backend/tests/test_live_supabase.py` (update)
- `backend/tests/test_rag.py` (add)
- `backend/tests/test_rag_integration.py` (add)
- `backend/tests/test_rag_providers.py` (add)
- `backend/tests/test_supabase_repository.py` (update)
- `docs/api-contract.md` (update)
- `docs/api-types.ts` (update)
- `frontend/README.md` (update)
- `frontend/src/App.tsx` (update)
- `frontend/src/services/api.ts` (update)
- `frontend/src/types/api.ts` (update)

No commit, push, deployment, paid resource creation, or bulk live indexing was performed.
