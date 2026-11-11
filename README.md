# 🎬🧠 TubeInsight AI — YouTube Learning Assistant

An AI-powered web application that helps users explore YouTube videos through text and voice questions. TubeInsight AI retrieves relevant transcript passages and generates answers with supporting excerpts and clickable timestamps.

## 📌 Project Overview

Long videos can make it difficult to find a specific explanation or revisit an important point. TubeInsight AI turns video transcripts into a searchable knowledge source, helping users ask questions, explore key ideas, and jump directly to relevant moments.

The application combines a React frontend, a FastAPI backend, retrieval-augmented generation (RAG), agent tools, and persistent conversation memory. Users can type a question or record it, review the transcription, and send it to the assistant.

## 🏗️ Project Architecture

```text

┌───────────────────── React + Vite Frontend ─────────────────────┐
│    Chat tab · Transcript tab · Video player · Audio recorder    │
└────────────────────────────────┬────────────────────────────────┘
                                 │  REST
┌────────────────────────────────▼────────────────────────────────┐
│                         FastAPI Backend                         │
│          Video processing · Chat · Audio transcription          │
└──────────┬─────────────────────┬─────────────────────┬──────────┘
           │                     │                     │
           ▼                     ▼                     ▼
       Supabase              Pinecone         OpenAI + LangGraph
    cache + memory         vector search       LLM · embeddings
                                                       │
                                                       ▼
                                                   LangSmith
                                                    tracing
                                                
```

Voice recordings are sent to the transcription endpoint first. The returned text appears in the question box for review before the user submits it to the chat.

## 📄 Data Sources

TubeInsight AI uses YouTube video transcripts as its knowledge source.

- Captions provide the video content and timestamps.
- Supabase caches transcripts for reuse.
- Pinecone stores embeddings of timestamped transcript chunks for semantic search.

Voice recordings are transcribed into user questions; they are separate from the video content used to generate answers.

## ✨ Main Features

- **YouTube Video Q&A** — Analyse a video and ask questions about its content.
- **Voice Questions** — Record a question, transcribe it, edit the text, and send it.
- **Timestamped Citations** — Read supporting excerpts and click timestamps to play the relevant moment.
- **Chat and Transcript Tabs** — Switch between the conversation and timestamped transcript.
- **Agent Tools** — Search transcripts, retrieve content by timestamp, and generate full-video summaries.
- **Persistent Conversation Memory** — Store conversation history in Supabase to support follow-up questions.
- **Transcript Caching** — Reuse saved transcripts instead of fetching the same captions repeatedly.
- **Loading Indicators** — Show progress during video analysis, answer generation, and transcription.
- **Recording Controls** — Start, stop, cancel, and review recordings, with a 60-second recording limit.
- **LangSmith Tracing** — Inspect agent runs and tool activity for debugging.

## 🧠 Model

### OpenAI Embeddings and Pinecone Retrieval

Timestamped transcript chunks are represented as embeddings and indexed in Pinecone. Relevant content is retrieved to support answers to the user's question.

**Reason for choosing this approach:** semantic retrieval helps locate relevant passages even when the question uses different wording from the transcript. Keeping timestamps with the chunks makes answers traceable to the video.

### OpenAI Answer Generation

The application uses an OpenAI language model to generate answers grounded in retrieved transcript content.

**Reason for choosing this approach:** combining generation with retrieved evidence supports natural-language explanations and source-backed answers without training a model from scratch.

### LangGraph Agent and Conversation Memory

The backend uses agent tools for transcript search, timestamp retrieval, and full-video summaries. Supabase stores conversation history for follow-up questions.

### Speech Recognition

The browser records a short audio question and uploads it to `POST /api/audio/transcribe`. The endpoint returns the transcribed text, an optional language value, and the model identifier. The frontend lets users review the text before sending it.

The configured backend determines the exact model versions used.

## Video Q&A Results

Manual checks on one video verified the following behaviours:

| Check | Observed result |
| --- | --- |
| Main-idea question | Returned an answer supported by transcript excerpts |
| Specific factual question | Correctly identified the meaning of “I” in the video's PRIME framework |
| Context-dependent follow-up | Connected “that step” to the preceding discussion of Interview |
| Unsupported question | Declined to answer and returned no sources |
| Ambiguous question in a new session | Declined to guess instead of assuming the previous session's context |
| Voice input | Recording, transcription, editing, and question submission worked in local testing |

These are functional checks, not a measured accuracy benchmark. Broader evaluation across multiple videos and question types remains to be completed.

## Transcript Retrieval and Conversation Memory

The assistant uses relevant video content and conversation history to interpret questions. Timestamp-based retrieval supports questions about a particular moment, while full-video summaries support broader requests.

Supabase provides two separate capabilities: cached video transcripts and persistent conversation memory. Starting a new session clears the frontend conversation state and pending recording or transcription activity.

## Approach

1. Accept a YouTube URL in the frontend.
2. Retrieve available captions locally or load a cached transcript.
3. Save the transcript in Supabase and index timestamped content in Pinecone.
4. Accept a typed question or transcribe a recorded question.
5. Use conversation context and agent tools to retrieve relevant video content.
6. Generate an answer with supporting excerpts and timestamps.
7. Display the answer and allow users to play cited moments.
8. Inspect agent execution through LangSmith traces.

## 🤖 AI-Powered Video Summarization

The full-video summary tool helps users understand the video's main ideas without reading the entire transcript. More specific questions use transcript search or timestamp-based retrieval to find supporting content.

Answers and summaries depend on the available transcript. When the requested information is unsupported, the assistant should state that it cannot determine the answer.

## Deployment

The frontend and backend are deployed separately on Vercel.

- 🚀 **Live application:** [TubeInsight AI](https://tubeinsight-ai.vercel.app/)
- **Backend:** [FastAPI service](https://tubeinsight-ai-backend.vercel.app/)
- **API documentation:** [Swagger UI](https://tubeinsight-ai-backend.vercel.app/docs)

### Current Transcript Caching Workflow

YouTube caption retrieval is blocked in the hosted backend environment. To use a new video on the deployed application:

1. Run the backend and frontend locally, with the frontend pointing to the local backend.
2. Analyse the new YouTube URL locally to fetch and cache its transcript in Supabase.
3. Ensure its transcript has also been indexed in Pinecone.
4. Open the deployed application and analyse the same URL.

The hosted backend can then use the cached, indexed content. Cached transcript storage alone does not guarantee that a video has been indexed.

### How to Run the Project Locally

**Prerequisites:** Python 3.11, Node.js with npm, and access to the configured OpenAI, Pinecone, Supabase, and LangSmith services.

#### 1. Start the backend

From the repository root in PowerShell:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure the backend environment using the [backend setup guide](backend/README.md). Use the project's actual environment configuration for service credentials, model settings, database access, and CORS. Keep secrets out of version control.

Start FastAPI:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open [local API documentation](http://localhost:8000/docs).

#### 2. Start the frontend

In a second PowerShell terminal, from the repository root:

```powershell
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
VITE_BACKEND_API_URL=http://localhost:8000
```

Ensure the backend CORS configuration allows the frontend's local origin. Start the frontend:

```powershell
npm run dev
```

Open the local URL printed by Vite. Restart Vite after changing frontend environment variables.

To use the hosted backend instead, set `VITE_BACKEND_API_URL` to `https://tubeinsight-ai-backend.vercel.app`. New video ingestion still requires the local caching workflow described above.

#### 3. Check the frontend

From `frontend`:

```powershell
npm run build
npm run lint
```

## Project Structure

```text
tubeinsight-ai/
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   └── AudioRecorder.tsx
│   │   ├── services/
│   │   │   ├── api.ts
│   │   │   └── http.ts
│   │   ├── types/
│   │   │   └── api.ts
│   │   ├── App.tsx
│   │   └── App.css
│   └── package.json
│
├── backend/
│   ├── app/
│   │   └── main.py
│   ├── requirements.txt
│   └── README.md
│
├── docs/
│   ├── api-contract.md
│   └── api-types.ts
│
└── README.md
```

## 🛠️ Technologies Used

| Category | Tools & Technologies |
| --- | --- |
| **Programming Languages** | Python, TypeScript |
| **Frontend** | React, Vite, Tailwind CSS, CSS |
| **Backend** | FastAPI, Pydantic |
| **Generative AI and Embeddings** | OpenAI |
| **Agent and RAG Frameworks** | LangChain, LangGraph |
| **Vector Database** | Pinecone |
| **Transcript Cache and Conversation Memory** | Supabase |
| **Voice Input** | Browser MediaRecorder API and backend speech transcription |
| **Tracing** | LangSmith |
| **Deployment** | Vercel |

## Limitations

- New videos must currently be analysed and indexed locally before they can be used on the hosted application.
- Answer coverage depends on transcript availability, caption quality, chunking, and retrieval quality.
- Transcript-based answers do not interpret visual-only information such as an on-screen diagram that is not described in the audio.
- Generated answers can still contain errors; users should review cited passages.
- Audio questions are limited to 60 seconds. Recording requires microphone permission and a supported browser in a secure context, such as HTTPS or localhost.
- Transcription can be affected by background noise, pronunciation, and recording quality.
- Agent execution and external services can introduce response delays.
- LangSmith tracing is implemented; a completed quantitative evaluation has not yet been confirmed.

## References

- [React documentation](https://react.dev/)
- [Vite documentation](https://vite.dev/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [OpenAI documentation](https://platform.openai.com/docs)
- [LangChain and LangGraph documentation](https://docs.langchain.com/)
- [LangSmith documentation](https://docs.langchain.com/langsmith/)
- [Pinecone documentation](https://docs.pinecone.io/)
- [Supabase documentation](https://supabase.com/docs)
- [MediaRecorder API](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)

## Authors

- Rayhan Patoary
- Anita Kiran

## License

This project was developed for educational purposes. No software license is specified in this README; see the repository's `LICENSE` file if one is provided.
