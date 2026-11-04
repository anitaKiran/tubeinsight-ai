import { useState } from "react";
import type { FormEvent } from "react";
import "./App.css";

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
};

function getYouTubeVideoId(value: string): string | null {
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    let videoId: string | null = null;

    if (hostname === "youtu.be") {
      videoId = url.pathname.split("/")[1];
    } else if (
      ["youtube.com", "www.youtube.com", "m.youtube.com"].includes(hostname)
    ) {
      const parts = url.pathname.split("/").filter(Boolean);

      if (url.pathname === "/watch") {
        videoId = url.searchParams.get("v");
      } else if (["shorts", "embed", "live"].includes(parts[0])) {
        videoId = parts[1];
      }
    }

    if (!["https:", "http:"].includes(url.protocol)) {
      return null;
    }

    return videoId && /^[a-zA-Z0-9_-]{11}$/.test(videoId)
      ? videoId
      : null;
  } catch {
    return null;
  }
}

function App() {
  const [videoUrl, setVideoUrl] = useState("");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);

  function handleLoadVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const extractedId = getYouTubeVideoId(videoUrl.trim());

    if (!extractedId) {
      setError("Enter a valid YouTube video link.");
      return;
    }

    setError("");
    setVideoId(extractedId);
    setMessages([]);
    setQuestion("");
  }

  function handleSendQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = question.trim();

    if (!text || !videoId) {
      return;
    }

    setMessages((previous) => [
      ...previous,
      {
        id: previous.length + 1,
        role: "user",
        text,
      },
      {
        id: previous.length + 2,
        role: "assistant",
        text: "Your question is ready. AI answers will be available once the backend is connected.",
      },
    ]);

    setQuestion("");
  }

  function handleReset() {
    setVideoUrl("");
    setVideoId(null);
    setError("");
    setQuestion("");
    setMessages([]);
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="VideoWise AI home">
          <span className="brand-icon" aria-hidden="true">
            ▶
          </span>

          <span>
            VideoWise <strong>AI</strong>
          </span>
        </a>

        <p className="sidebar-description">
          Turn video content into clear answers.
        </p>

        <button className="new-session-button" onClick={handleReset}>
          + New session
        </button>

        <div className="sidebar-section">
          <p className="sidebar-label">YOUR WORKSPACE</p>
          <div className="workspace-item">Video assistant</div>
        </div>

        <div className="sidebar-footer">
          <span className="status-dot" />
          Frontend preview
        </div>
      </aside>

      <main className="main-content">
        <header className="page-header">
          <div>
            <p className="eyebrow">YOUR VIDEO LEARNING COMPANION</p>
            <h1>Watch less. Understand more.</h1>
            <p className="page-description">
              Add a YouTube video, ask questions, and explore its key ideas.
            </p>
          </div>

          <span className="preview-badge">Preview</span>
        </header>

        <section className="panel video-input-panel">
          <h2>Start with a video</h2>

          <form onSubmit={handleLoadVideo}>
            <label htmlFor="video-url">YouTube video link</label>

            <div className="url-form-row">
              <input
                id="video-url"
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={videoUrl}
                onChange={(event) => setVideoUrl(event.target.value)}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "video-error" : "video-help"}
                required
              />

              <button className="primary-button" type="submit">
                Analyze video
              </button>
            </div>

            {error ? (
              <p id="video-error" className="error-text" role="alert">
                {error}
              </p>
            ) : (
              <p id="video-help" className="helper-text">
                Choose one video to start your learning session.
              </p>
            )}
          </form>
        </section>

        <div className="workspace-grid">
          <section className="panel video-panel">
            <div className="panel-heading">
              <h2>Your video</h2>
              {videoId && <span className="selected-badge">Selected</span>}
            </div>

            {videoId ? (
              <div className="selected-video">
                <img
                  className="video-thumbnail"
                  src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
                  alt="Selected YouTube video thumbnail"
                />

                <p className="video-id">Video ID: {videoId}</p>

                <a
                  className="video-link"
                  href={`https://www.youtube.com/watch?v=${videoId}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open video on YouTube ↗
                </a>

                <p className="helper-text">
                  Transcript processing will be added when the backend is
                  connected.
                </p>
              </div>
            ) : (
              <div className="empty-state">
                <span className="empty-icon" aria-hidden="true">
                  ▶
                </span>
                <h3>Your next discovery starts here</h3>
                <p>Paste a YouTube link above to select a video.</p>
              </div>
            )}
          </section>

          <section className="panel chat-panel">
            <div className="panel-heading">
              <h2>Ask VideoWise</h2>
              <span className="chat-label">Video Q&amp;A</span>
            </div>

            <div
              className="messages"
              role="log"
              aria-label="Conversation"
              aria-live="polite"
            >
              {messages.length === 0 ? (
                <div className="chat-empty-state">
                  <span className="chat-symbol" aria-hidden="true">
                    ✦
                  </span>
                  <h3>Make the video make sense</h3>
                  <p>
                    {videoId
                      ? "Try typing a question about your selected video."
                      : "Select a video to start asking questions."}
                  </p>
                </div>
              ) : (
                messages.map((message) => (
                  <article
                    key={message.id}
                    className={`message message-${message.role}`}
                  >
                    <span className="message-author">
                      {message.role === "user" ? "You" : "VideoWise AI"}
                    </span>
                    <p>{message.text}</p>
                  </article>
                ))
              )}
            </div>

            <form className="question-form" onSubmit={handleSendQuestion}>
              <label className="sr-only" htmlFor="question">
                Your question
              </label>

              <input
                id="question"
                type="text"
                placeholder={
                  videoId ? "Ask about this video..." : "Select a video first"
                }
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={!videoId}
                maxLength={2000}
              />

              <button
                className="primary-button"
                type="submit"
                disabled={!videoId || !question.trim()}
              >
                Send
              </button>
            </form>

            <p className="chat-disclaimer">
              Preview mode: responses are placeholders.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;