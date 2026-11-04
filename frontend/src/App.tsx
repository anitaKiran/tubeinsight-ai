import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { checkHealth, processVideo } from "./services/api";
import type { ProcessVideoResponse } from "./types/api";
import "./App.css";

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
};

type ConnectionStatus = "checking" | "connected" | "unavailable";

function formatTimestamp(seconds: number): string {
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;

  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function App() {
  const [videoUrl, setVideoUrl] = useState("");
  const [processedVideo, setProcessedVideo] =
    useState<ProcessVideoResponse | null>(null);

  const [error, setError] = useState("");
  const [isVideoLoading, setIsVideoLoading] = useState(false);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);

  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("checking");

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);

  const videoRequestRef = useRef<AbortController | null>(null);
  const videoRequestIdRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const video = processedVideo?.video ?? null;
  const isMock = processedVideo?.mode === "mock";

  useEffect(() => {
    const controller = new AbortController();

    checkHealth(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) {
          setConnectionStatus("connected");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setConnectionStatus("unavailable");
        }
      });

    return () => {
      controller.abort();
      videoRequestRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [messages]);

  async function handleLoadVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const url = videoUrl.trim();

    if (!url || isVideoLoading) {
      return;
    }

    videoRequestRef.current?.abort();

    const controller = new AbortController();
    videoRequestRef.current = controller;

    const requestId = ++videoRequestIdRef.current;

    setIsVideoLoading(true);
    setError("");
    setProcessedVideo(null);
    setMessages([]);
    setQuestion("");
    setThumbnailFailed(false);

    try {
      const result = await processVideo(url, controller.signal);

      if (
        controller.signal.aborted ||
        requestId !== videoRequestIdRef.current
      ) {
        return;
      }

      setProcessedVideo(result);
      setConnectionStatus("connected");
    } catch (requestError) {
      if (
        controller.signal.aborted ||
        requestId !== videoRequestIdRef.current
      ) {
        return;
      }

      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to process the video. Please try again.",
      );
    } finally {
      if (requestId === videoRequestIdRef.current) {
        setIsVideoLoading(false);
        videoRequestRef.current = null;
      }
    }
  }

  function handleSendQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = question.trim();

    if (!text || !video || isVideoLoading) {
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
        text: "This is a frontend placeholder. The chat API is not connected yet, so no question has been sent to the backend.",
      },
    ]);

    setQuestion("");
  }

  function handleReset() {
    videoRequestRef.current?.abort();
    videoRequestRef.current = null;
    videoRequestIdRef.current += 1;

    setVideoUrl("");
    setProcessedVideo(null);
    setError("");
    setQuestion("");
    setMessages([]);
    setIsVideoLoading(false);
    setThumbnailFailed(false);
  }

  const connectionLabel =
    connectionStatus === "checking"
      ? "Checking backend..."
      : connectionStatus === "connected"
        ? "Backend connected · Mock mode"
        : "Backend unavailable";

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

        <button
          className="new-session-button"
          type="button"
          onClick={handleReset}
        >
          + New session
        </button>

        <div className="sidebar-section">
          <p className="sidebar-label">YOUR WORKSPACE</p>
          <div className="workspace-item">Video assistant</div>
        </div>

        <div className="sidebar-footer" role="status">
          <span
            className="status-dot"
            aria-hidden="true"
            style={{
              backgroundColor:
                connectionStatus === "connected"
                  ? "#287754"
                  : connectionStatus === "checking"
                    ? "#b7791f"
                    : "#e53935",
            }}
          />

          {connectionLabel}
        </div>
      </aside>

      <main className="main-content">
        <header className="page-header">
          <div>
            <p className="eyebrow">YOUR VIDEO LEARNING COMPANION</p>

            <h1>Your videos. Clearer answers.</h1>

            <p className="page-description">
              Add a YouTube video, ask questions, and explore its key ideas.
            </p>
          </div>

          <span className="preview-badge">Mock API preview</span>
        </header>

        <section
          className="panel video-input-panel"
          aria-labelledby="video-input-heading"
        >
          <h2 id="video-input-heading">Start with a video</h2>

          <form onSubmit={handleLoadVideo}>
            <label htmlFor="video-url">YouTube video link</label>

            <div className="url-form-row">
              <input
                id="video-url"
                type="url"
                placeholder="https://www.youtube.com/watch?v=..."
                value={videoUrl}
                onChange={(event) => setVideoUrl(event.target.value)}
                disabled={isVideoLoading}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "video-error" : "video-help"}
                required
              />

              <button
                className="primary-button"
                type="submit"
                disabled={isVideoLoading || !videoUrl.trim()}
              >
                {isVideoLoading ? "Processing..." : "Analyse video"}
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
          <section
            className="panel video-panel"
            aria-labelledby="video-heading"
            aria-busy={isVideoLoading}
          >
            <div className="panel-heading">
              <h2 id="video-heading">Your video</h2>

              {video && (
                <span className="selected-badge">
                  {isMock ? "Demo ready" : "Ready"}
                </span>
              )}
            </div>

            {isVideoLoading ? (
              <div className="empty-state" role="status">
                <span className="empty-icon" aria-hidden="true">
                  ▶
                </span>

                <h3>Processing your video</h3>

                <p>Waiting for the backend response...</p>
              </div>
            ) : video && processedVideo ? (
              <div className="selected-video">
                {isMock && (
                  <p className="mock-notice" role="note">
                    Mock / simulated content: the title, duration,
                    transcript, and answers are demo data. They do not
                    describe the linked video. Demo timestamps are for
                    interaction testing only.
                  </p>
                )}

                {!thumbnailFailed ? (
                  <img
                    className="video-thumbnail"
                    src={video.thumbnail_url}
                    alt="Thumbnail of the linked YouTube video"
                    onError={() => setThumbnailFailed(true)}
                  />
                ) : (
                  <div className="empty-state">
                    <p>Thumbnail unavailable. You can still open the video.</p>
                  </div>
                )}

                <h3 className="video-title">
                  {video.title ?? "Untitled video"}
                </h3>

                {video.duration_seconds !== null && (
                  <p className="helper-text">
                    {isMock ? "Simulated duration" : "Duration"}:{" "}
                    {formatTimestamp(video.duration_seconds)}
                  </p>
                )}

                <a
                  className="video-link"
                  href={video.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open actual video on YouTube ↗
                </a>

                <details className="transcript-preview">
                  <summary>
                    {isMock ? "Simulated transcript" : "Transcript"}
                  </summary>

                  {processedVideo.transcript.length === 0 ? (
                    <p className="helper-text">
                      No transcript segments were returned.
                    </p>
                  ) : (
                    processedVideo.transcript.map((segment, index) => (
                      <div className="transcript-segment" key={index}>
                        <a
                          href={`https://www.youtube.com/watch?v=${video.id}&t=${Math.floor(
                            segment.start_seconds,
                          )}s`}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`Open video at ${formatTimestamp(
                            segment.start_seconds,
                          )}${isMock ? "; simulated source timestamp" : ""}`}
                        >
                          {formatTimestamp(segment.start_seconds)}
                        </a>

                        <p>{segment.text}</p>
                      </div>
                    ))
                  )}
                </details>
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

          <section
            className="panel chat-panel"
            aria-labelledby="chat-heading"
          >
            <div className="panel-heading">
              <h2 id="chat-heading">Ask VideoWise</h2>
              <span className="chat-label">Video Q&amp;A</span>
            </div>

            <p className="helper-text">
              Frontend preview: chat responses are placeholders.
            </p>

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
                    {video
                      ? "Try typing a question to preview the chat layout."
                      : "Process a video to start previewing the chat."}
                  </p>
                </div>
              ) : (
                messages.map((message) => (
                  <article
                    key={message.id}
                    className={`message message-${message.role}`}
                  >
                    <span className="message-author">
                      {message.role === "user"
                        ? "You"
                        : "VideoWise AI · Preview"}
                    </span>

                    <p>{message.text}</p>
                  </article>
                ))
              )}

              <div ref={messagesEndRef} />
            </div>

            <form
              className="question-form"
              onSubmit={handleSendQuestion}
            >
              <label className="sr-only" htmlFor="question">
                Your question
              </label>

              <input
                id="question"
                type="text"
                placeholder={
                  video
                    ? "Ask about this video..."
                    : "Process a video first"
                }
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={!video || isVideoLoading}
                maxLength={2000}
              />

              <button
                className="primary-button"
                type="submit"
                disabled={
                  !video || isVideoLoading || !question.trim()
                }
              >
                Send
              </button>
            </form>

            <p className="chat-disclaimer">
              Chat API integration is the next milestone.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;