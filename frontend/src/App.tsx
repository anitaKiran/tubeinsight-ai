import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  askQuestion,
  checkHealth,
  processVideo,
} from "./services/api";
import type {
  ProcessVideoResponse,
  TranscriptSegment,
} from "./types/api";
import "./App.css";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: TranscriptSegment[];
  mode?: "mock" | "real";
};

type ConnectionStatus = "checking" | "connected" | "unavailable";

function formatTimestamp(seconds: number): string {
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function App() {
  const [videoUrl, setVideoUrl] = useState("");
  const [processedVideo, setProcessedVideo] =
    useState<ProcessVideoResponse | null>(null);
  const [error, setError] = useState("");
  const [isVideoLoading, setIsVideoLoading] = useState(false);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("checking");

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");

  const videoRequestRef = useRef<AbortController | null>(null);
  const videoRequestIdRef = useRef(0);
  const chatRequestRef = useRef<AbortController | null>(null);
  const chatRequestIdRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const playerRef = useRef<HTMLIFrameElement | null>(null);

  const video = processedVideo?.video ?? null;
  const isMock = processedVideo?.mode === "mock";

  const [activeTab, setActiveTab] = useState<"chat" | "transcript">("chat");

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
      chatRequestRef.current?.abort();
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

  function playAtTimestamp(seconds: number) {
  if (!video || !playerRef.current || !Number.isFinite(seconds)) {
    return;
  }

  const start = Math.max(0, Math.floor(seconds));

  playerRef.current.src =
    `https://www.youtube.com/embed/${video.id}?start=${start}&autoplay=1`;

  playerRef.current.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
}

  function resetChat() {
    chatRequestRef.current?.abort();
    chatRequestRef.current = null;
    chatRequestIdRef.current += 1;

    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setChatError("");
    setIsChatLoading(false);
    setActiveTab("chat");
  }

  async function handleLoadVideo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const url = videoUrl.trim();

    if (!url || videoRequestRef.current) {
      return;
    }

    const controller = new AbortController();
    videoRequestRef.current = controller;
    const requestId = ++videoRequestIdRef.current;

    setIsVideoLoading(true);
    setError("");
    setProcessedVideo(null);
    resetChat();

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

  async function handleSendQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const text = question.trim();

    if (!text || !video || isVideoLoading || chatRequestRef.current) {
      return;
    }

    const controller = new AbortController();
    chatRequestRef.current = controller;
    const requestId = ++chatRequestIdRef.current;

    setChatError("");
    setIsChatLoading(true);

    try {
      const result = await askQuestion(
        {
          video_id: video.id,
          question: text,
          conversation_id: conversationId,
        },
        controller.signal,
      );

      if (
        controller.signal.aborted ||
        requestId !== chatRequestIdRef.current
      ) {
        return;
      }

      setConversationId(result.conversation_id);

      setMessages((previous) => [
        ...previous,
        {
          id: crypto.randomUUID(),
          role: "user",
          text,
        },
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: result.answer,
          sources: result.sources,
          mode: result.mode,
        },
      ]);

      setQuestion("");
    } catch (requestError) {
      if (
        controller.signal.aborted ||
        requestId !== chatRequestIdRef.current
      ) {
        return;
      }

      if (requestError instanceof ApiError) {
        if (requestError.code === "CONVERSATION_NOT_FOUND") {
          setConversationId(null);
          setMessages([]);
          setChatError(
            "This conversation has expired. Send your question again to start a new conversation.",
          );
        } else if (requestError.code === "VIDEO_NOT_FOUND") {
          setProcessedVideo(null);
          setConversationId(null);
          setMessages([]);
          setChatError(
            "The backend no longer has this video. Analyse it again before asking a question.",
          );
        } else {
          setChatError(requestError.message);
        }
      } else {
        setChatError("Unable to send your question. Please try again.");
      }
    } finally {
      if (requestId === chatRequestIdRef.current) {
        setIsChatLoading(false);
        chatRequestRef.current = null;
      }
    }
  }

  function handleReset() {
    videoRequestRef.current?.abort();
    videoRequestRef.current = null;
    videoRequestIdRef.current += 1;

    resetChat();
    setVideoUrl("");
    setProcessedVideo(null);
    setError("");
    setIsVideoLoading(false);
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
          <span className="brand-icon" aria-hidden="true">▶</span>
          <span>VideoWise <strong>AI</strong></span>
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
                <span className="empty-icon" aria-hidden="true">▶</span>
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

                <div className="video-player-container">
                 <iframe
                    ref={playerRef}
                    key={video.id}
                    className="video-player"
                    src={`https://www.youtube.com/embed/${video.id}`}
                    title={video.title ?? "Selected YouTube video"}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    referrerPolicy="strict-origin-when-cross-origin"
                    allowFullScreen
                  />
                </div>

                <p className="helper-text">
                  If playback is unavailable here, use the YouTube link below.
                </p>

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
              </div>
            ) : (
              <div className="empty-state">
                <span className="empty-icon" aria-hidden="true">▶</span>
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
              <h2 id="chat-heading">Explore this video</h2>
              <span className="chat-label">Video Q&amp;A</span>
            </div>
          
          <div className="workspace-tabs" aria-label="Video views">
            <button
            type="button"
            className={`workspace-tab ${activeTab === "chat" ? "is-active" : ""}`}
            aria-pressed={activeTab === "chat"}
            aria-controls="chat-view"
            onClick={() => setActiveTab("chat")}
          >
            Chat
           </button>
           
           <button
              type="button"
              className={`workspace-tab ${activeTab === "transcript" ? "is-active" : ""}`}
              aria-pressed={activeTab === "transcript"}
              aria-controls="transcript-view"
              onClick={() => setActiveTab("transcript")}
            >
            Transcript
          </button>
        </div>

            {isMock && (
              <p className="mock-notice" role="note">
                Answers and sources are simulated. They do not describe
                the linked video.
              </p>
            )}

          <div
              id="chat-view"
              className="chat-view"
              hidden={activeTab !== "chat"}
            >
            <div
              className="messages"
              role="log"
              aria-label="Conversation"
              aria-live="polite"
            >
              {messages.length === 0 ? (
                <div className="chat-empty-state">
                  <span className="chat-symbol" aria-hidden="true">✦</span>
                  <h3>Make the video make sense</h3>
                  <p>
                    {video
                      ? "Ask a question about the selected video."
                      : "Process a video to start asking questions."}
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
                        : message.mode === "mock"
                          ? "VideoWise AI · Simulated"
                          : "VideoWise AI"}
                    </span>

                    <p>{message.text}</p>

                    {video &&
                      message.sources &&
                      message.sources.length > 0 && (
                        <div className="answer-sources">
                          <span className="sources-label">
                            {message.mode === "mock"
                              ? "Simulated sources"
                              : "Sources"}
                          </span>

                          {message.sources.map((source, index) => (
                            <a
                              className="source-card"
                              onClick={(event) => {
                              if (
                                  event.ctrlKey ||
                                  event.metaKey ||
                                  event.shiftKey ||
                                  event.altKey
                                ) {
                                  return;
                              }
                            event.preventDefault();
                            playAtTimestamp(source.start_seconds);
                          }}
                              key={`${source.start_seconds}-${index}`}
                              href={`https://www.youtube.com/watch?v=${video.id}&t=${Math.floor(source.start_seconds)}s`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <span className="source-timestamp">
                                ▶ {formatTimestamp(source.start_seconds)}
                              </span>
                              <span>{source.text}</span>
                            </a>
                          ))}
                        </div>
                      )}
                  </article>
                ))
              )}

              <div ref={messagesEndRef} />
            </div>

            {isChatLoading && (
              <p className="helper-text" role="status">
                Waiting for an answer...
              </p>
            )}

            {chatError && (
              <p id="chat-error" className="error-text" role="alert">
                {chatError}
              </p>
            )}

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
                  video ? "Ask about this video..." : "Process a video first"
                }
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={!video || isVideoLoading || isChatLoading}
                aria-describedby={chatError ? "chat-error" : undefined}
                maxLength={2000}
              />

              <button
                className="primary-button"
                type="submit"
                disabled={
                  !video ||
                  isVideoLoading ||
                  isChatLoading ||
                  !question.trim()
                }
              >
                {isChatLoading ? "Sending..." : "Send"}
              </button>
            </form>

            <p className="chat-disclaimer">
              Check the sources when reviewing an answer.
            </p>
            </div>

            <div
              id="transcript-view"
              className="transcript-view"
              hidden={activeTab !== "transcript"}
            >
            {!video || !processedVideo ? (
              <div className="chat-empty-state">
                <h3>No transcript yet</h3>
                <p>Analyse a video to view its transcript.</p>
              </div>
  ) : processedVideo.transcript.length === 0 ? (
    <div className="chat-empty-state">
      <h3>Transcript unavailable</h3>
      <p>No transcript segments were returned for this video.</p>
    </div>
  ) : (
    <>
      <p className="helper-text">
        {processedVideo.transcript.length} transcript segments.
        Select a timestamp to play that moment in the video above.
      </p>

      <div className="transcript-list">
        {processedVideo.transcript.map((segment, index) => (
          <div
            className="transcript-segment"
            key={`${segment.start_seconds}-${index}`}
          >
            <a
               onClick={(event) => {
                if (
                  event.ctrlKey ||
                  event.metaKey ||
                  event.shiftKey ||
                  event.altKey
                ) {
                  return;
                }
                event.preventDefault();
                playAtTimestamp(segment.start_seconds);
              }}
              href={`https://www.youtube.com/watch?v=${video.id}&t=${Math.floor(
                segment.start_seconds,
              )}s`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open video at ${formatTimestamp(
                segment.start_seconds,
              )}${isMock ? "; simulated timestamp" : ""}`}
            >
              {formatTimestamp(segment.start_seconds)}
            </a>

            <p>{segment.text}</p>
          </div>
        ))}
      </div>
    </>
  )}
</div>


          </section>
        </div>
      </main>
    </div>
  );
}

export default App;