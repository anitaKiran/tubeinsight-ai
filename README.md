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
