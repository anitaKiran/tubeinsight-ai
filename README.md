<<<<<<< Updated upstream
# VideoWise AI — YouTube Learning Assistant 🎬🧠

Ask questions about any YouTube video and get answers with links to the exact moment in the video.

TubeMind transcribes videos (captions or Whisper), stores them as timestamped chunks in a vector database, and uses a LangGraph agent with tools and memory to answer questions by text or voice. Performance is traced and evaluated with LangSmith.

**Features**
- Paste a YouTube link and chat with the video
- Voice questions via Whisper speech recognition
- Answers with clickable timestamp citations
- Agent with tools: ingest, search, summarize, metadata
- Conversation memory for follow-up questions

**Tech stack:** Python, LangChain, LangGraph, LangSmith, OpenAI/HuggingFace, Whisper, ChromaDB, Streamlit
=======
# videowise-ai
AI-powered YouTube learning assistant with video Q&amp;A, timestamped answers, audio transcription, and conversational memory using LangChain and RAG.

## Day 1: mock backend

The FastAPI backend is ready for React integration with simulated video data and
chat responses. It does not yet use AI services, YouTube extraction, or a database.

- [Backend setup, startup, tests, and curl examples](backend/README.md)
- [API contract for frontend integration](docs/api-contract.md)
- [Copyable TypeScript API interfaces](docs/api-types.ts)

From the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/docs> to try the API. The frontend is managed separately.
>>>>>>> Stashed changes
