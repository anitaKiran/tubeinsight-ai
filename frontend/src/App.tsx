import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import AudioRecorder from "./components/AudioRecorder";
import Icon from "./components/Icon";
import AnswerText from "./components/AnswerText";
import {
  ApiError,
  askQuestion,
  checkHealth,
  processVideo,
  summarizeVideo,
} from "./services/api";
import type {
  ChatResponse,
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

type Tab = "chat" | "transcript" | "summary";
const tabs: Tab[] = ["chat", "transcript", "summary"];

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

  const [activeTab, setActiveTab] = useState<Tab>("chat");

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [summary, setSummary] = useState<ChatResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const summaryRequestRef = useRef<AbortController | null>(null);
  const summaryRequestIdRef = useRef(0);

  const [recordingSession, setRecordingSession] = useState(0);

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
      summaryRequestRef.current?.abort();
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

  function clearSummary() {
    summaryRequestRef.current?.abort();
    summaryRequestRef.current = null;
    summaryRequestIdRef.current += 1;
    setSummary(null);
    setSummaryError("");
    setSummaryLoading(false);
  }

  async function loadSummary() {
    if (!video || isVideoLoading || summaryRequestRef.current || summary) return;
    const controller = new AbortController();
    const requestId = ++summaryRequestIdRef.current;
    summaryRequestRef.current = controller;
    setSummaryLoading(true);
    setSummaryError("");
    try {
      const result = await summarizeVideo(video.id, controller.signal);
      if (controller.signal.aborted || requestId !== summaryRequestIdRef.current) return;
      if (!result.answer.trim()) throw new Error("No summary was returned. Please try again.");
      setSummary(result);
    } catch (requestError) {
      if (controller.signal.aborted || requestId !== summaryRequestIdRef.current) return;
      setSummaryError(requestError instanceof Error ? requestError.message : "Unable to generate the summary. Please try again.");
    } finally {
      if (requestId === summaryRequestIdRef.current) {
        summaryRequestRef.current = null;
        setSummaryLoading(false);
      }
    }
  }

  function openTab(tab: Tab) {
    setActiveTab(tab);
    if (tab === "summary") void loadSummary();
  }

  function suggestQuestion(text: string) {
    // Reset a recorder in progress before filling the draft.
    setRecordingSession((current) => current + 1);
    setQuestion(text);
    setChatError("");
    setActiveTab("chat");
    requestAnimationFrame(() => document.getElementById("question")?.focus());
  }

  useEffect(() => {
    if (!sidebarOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSidebarOpen(false);
        document.getElementById("sidebar-toggle")?.focus();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [sidebarOpen]);

  function resetChat() {
    clearSummary();
    chatRequestRef.current?.abort();
    chatRequestRef.current = null;
    chatRequestIdRef.current += 1;

    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setChatError("");
    setIsChatLoading(false);
    setActiveTab("chat");
    setRecordingSession((current) => current + 1);
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
          clearSummary();
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
        ? "Backend connected"
        : "Backend unavailable";

  function sources(items: TranscriptSegment[], simulated = false) {
    if (!video || items.length === 0) return null;
    return (
      <div className="answer-sources">
        <span className="sources-label">{simulated ? "Simulated sources" : "From the video"}</span>
        {items.map((source, index) => (
          <a className="source-card" key={`${source.start_seconds}-${index}`}
            href={`https://www.youtube.com/watch?v=${video.id}&t=${Math.floor(source.start_seconds)}s`}
            target="_blank" rel="noopener noreferrer"
            onClick={(event) => {
              if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              playAtTimestamp(source.start_seconds);
            }}>
            <span className="source-timestamp"><Icon name="play" size={13} />{formatTimestamp(source.start_seconds)}</span>
            <span className="source-excerpt" title={source.text}>{source.text}</span>
            <Icon name="arrow" size={15} />
          </a>
        ))}
      </div>
    );
  }

  return (
    <div className="app-layout">
      <aside id="workspace-sidebar" className={`sidebar${sidebarOpen ? " is-open" : ""}`} aria-label="Workspace navigation">
        <a className="brand" href="/" aria-label="TubeInsight AI home" title="TubeInsight AI">
          <span className="brand-icon"><Icon name="play" size={24} /></span>
          <span className="sidebar-detail">TubeInsight <strong>AI</strong></span>
        </a>
        <button id="sidebar-toggle" className="sidebar-toggle rail-action" type="button"
          aria-expanded={sidebarOpen} aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          aria-controls="sidebar-details" title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          onClick={() => setSidebarOpen((open) => !open)}>
          <Icon name={sidebarOpen ? "close" : "menu"} /><span className="sidebar-detail">Close menu</span>
        </button>
        <button className="new-session-button rail-action" type="button" title="New session"
          aria-label="New session" onClick={() => { handleReset(); setSidebarOpen(false); }}>
          <Icon name="plus" /><span className="sidebar-detail">New session</span>
        </button>
        <div id="sidebar-details" className="sidebar-description sidebar-detail" hidden={!sidebarOpen}>
          Turn video content into clear answers.
        </div>
        <nav aria-label="Current workspace">
          <a className="workspace-item rail-action" href="#workspace" aria-current="page" aria-label="Video assistant" title="Video assistant"
            onClick={() => setSidebarOpen(false)}>
            <Icon name="video" /><span className="sidebar-detail">Video assistant</span>
          </a>
        </nav>
        <div className="sidebar-footer" role="status" title={connectionLabel}>
          <span className={`status-dot status-${connectionStatus}`} aria-hidden="true" />
          <span className={sidebarOpen ? "" : "sr-only"}>{connectionLabel}</span>
        </div>
      </aside>
      {sidebarOpen && <button type="button" className="sidebar-backdrop" aria-label="Close menu" onClick={() => setSidebarOpen(false)} />}

      <main className="main-content">
        <header className="page-header">
          <div>
            <p className="eyebrow">YOUR VIDEO LEARNING COMPANION</p>
            <h1>Your videos. Clearer answers.</h1>
            <p className="page-description">Add a YouTube video, ask questions, and explore its key ideas.</p>
          </div>
          <span className="preview-badge"><Icon name="spark" size={15} /> Video Q&amp;A</span>
        </header>

        <section className="panel video-input-panel" aria-labelledby="video-input-heading">
          <h2 id="video-input-heading">Start with a video</h2>
          <form onSubmit={handleLoadVideo}>
            <label htmlFor="video-url">YouTube video link</label>
            <div className="url-form-row">
              <div className="url-input-wrap">
                <span className="url-play-icon"><Icon name="play" size={17} /></span>
                <input id="video-url" type="url" placeholder="https://www.youtube.com/watch?v=..."
                  value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)}
                  disabled={isVideoLoading} aria-invalid={Boolean(error)}
                  aria-describedby={error ? "video-error" : "video-help"} required />
              </div>
              <button className="primary-button" type="submit" disabled={isVideoLoading} aria-busy={isVideoLoading}>
                {isVideoLoading ? <><span className="button-spinner" aria-hidden="true" />Analysing video…</> : "Analyse video"}
              </button>
            </div>
            {error ? <p id="video-error" className="error-text" role="alert">{error}</p>
              : <p id="video-help" className="helper-text">Choose one video to start your learning session.</p>}
          </form>
        </section>

        <div id="workspace" className="workspace-grid">
          <section className="panel video-panel" aria-labelledby="video-heading" aria-busy={isVideoLoading}>
            <div className="video-heading-wrap">
              <p className="section-eyebrow">YOUR VIDEO</p>
              <h2 id="video-heading" className="video-title">{video?.title ?? (video ? "Untitled video" : "A little curiosity goes a long way")}</h2>
              {video && <div className="video-meta">
                {video.duration_seconds !== null && <span><Icon name="clock" size={16} />{formatTimestamp(video.duration_seconds)}{isMock ? " · simulated" : ""}</span>}
                <span className="selected-badge"><span className="ready-dot" />{isMock ? "Demo ready" : "Transcript ready"}</span>
                <a className="video-link" href={video.url} target="_blank" rel="noopener noreferrer">YouTube <Icon name="arrow" size={14} /></a>
              </div>}
            </div>
            {isMock && <p className="mock-notice" role="note">Mock / simulated content: the title, duration, transcript and answers are demo data. They do not describe the linked video.</p>}
            {isVideoLoading ? <div className="empty-state video-empty" role="status">
              <span className="chat-loading-spinner" aria-hidden="true" /><h3>Analysing your video</h3><p>Preparing the transcript for your questions.</p>
            </div> : video ? <>
              <div className="video-player-container">
                <iframe ref={playerRef} key={video.id} className="video-player"
                  src={`https://www.youtube.com/embed/${video.id}`} title={video.title ?? "Selected YouTube video"}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  referrerPolicy="strict-origin-when-cross-origin" allowFullScreen />
              </div>
              <p className="playback-help">Playback unavailable? <a href={video.url} target="_blank" rel="noopener noreferrer">Watch on YouTube <Icon name="arrow" size={12} /></a></p>
            </> : <div className="empty-state video-empty">
              <span className="empty-icon"><Icon name="play" size={36} /></span><h3>Your next discovery starts here</h3><p>Paste a YouTube link above to select a video.</p>
            </div>}

            <div className="explore-actions" aria-labelledby="explore-heading">
              <h3 id="explore-heading"><Icon name="spark" size={18} /> Explore the key ideas</h3>
              <div className="suggestion-buttons">
                <button type="button" disabled={!video || isVideoLoading} onClick={() => openTab("summary")}>
                  <Icon name="list" /><span>Summarise this video</span>
                </button>
                <button type="button" disabled={!video || isVideoLoading || isChatLoading}
                  onClick={() => suggestQuestion("Explain the key concepts in this video in simple terms.")}>
                  <Icon name="layers" /><span>Explain the key concepts</span>
                </button>
                <button type="button" disabled={!video || isVideoLoading || isChatLoading}
                  onClick={() => suggestQuestion("What example does the speaker give to explain a main idea in this video?")}>
                  <Icon name="bulb" /><span>Find an example</span>
                </button>
              </div>
            </div>
          </section>

          <section className="panel chat-panel" aria-labelledby="chat-heading">
            <div className="chat-panel-header"><div><p className="section-eyebrow">YOUR LEARNING SPACE</p><h2 id="chat-heading">Ask TubeInsight</h2></div><span className="assistant-mark"><Icon name="spark" size={21} /></span></div>
            <div className="workspace-tabs" role="tablist" aria-label="Video views"
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const index = tabs.indexOf(activeTab);
                const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
                openTab(tabs[next]);
                event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
              }}>
              {tabs.map((tab) => <button key={tab} id={`${tab}-tab`} type="button" role="tab"
                className={`workspace-tab${activeTab === tab ? " is-active" : ""}`} aria-selected={activeTab === tab}
                aria-controls={`${tab}-view`} tabIndex={activeTab === tab ? 0 : -1} onClick={() => openTab(tab)}>
                {tab === "chat" ? "Chat" : tab === "transcript" ? "Transcript" : "Summary"}
              </button>)}
            </div>
            {isMock && <p className="mock-notice" role="note">Answers and sources are simulated.</p>}

            <div id="chat-view" role="tabpanel" aria-labelledby="chat-tab" className="chat-view" hidden={activeTab !== "chat"}>
              <div className="messages" role="log" aria-label="Conversation" aria-live="polite">
                {messages.length === 0 ? <div className="chat-empty-state">
                  <span className="chat-symbol"><Icon name="spark" size={30} /></span><h3>Make the video make sense</h3>
                  <p>{video ? "Ask a question, follow an idea, or try a prompt below the video." : "Analyse a video to start asking questions."}</p>
                </div> : messages.map((message) => <article key={message.id} className={`message message-${message.role}`}>
                  <span className="message-author">{message.role === "user" ? "You" : <><span className="answer-avatar"><Icon name="play" size={13} /></span>{message.mode === "mock" ? "TubeInsight AI · Simulated" : "TubeInsight AI"}</>}</span>
                  <div className="message-body"><AnswerText text={message.text} /></div>
                  {message.sources && sources(message.sources, message.mode === "mock")}
                </article>)}
                <div ref={messagesEndRef} />
              </div>
              {isChatLoading && <div className="chat-loading" role="status" aria-live="polite">
                <span className="chat-loading-spinner" aria-hidden="true" /><div><p className="chat-loading-title">Preparing your answer…</p><p className="chat-loading-description">Finding the relevant video content.</p></div>
              </div>}
              <div className="composer-area">
                {activeTab === "chat" && <AudioRecorder key={`${recordingSession}-${video?.id ?? "none"}-${isChatLoading}-${isVideoLoading}`}
                  question={question} onQuestionChange={setQuestion} onSubmit={handleSendQuestion}
                  disabled={!video || isVideoLoading || isChatLoading} sending={isChatLoading} errorId={chatError ? "chat-error" : undefined} />}
                {chatError && <p id="chat-error" className="error-text" role="alert">{chatError}</p>}
              </div>
            </div>

            <div id="transcript-view" role="tabpanel" aria-labelledby="transcript-tab" className="transcript-view" hidden={activeTab !== "transcript"} tabIndex={0}>
              {!video || !processedVideo ? <div className="chat-empty-state"><span className="chat-symbol"><Icon name="list" size={28} /></span><h3>No transcript yet</h3><p>Analyse a video to explore its transcript.</p></div>
                : processedVideo.transcript.length === 0 ? <div className="chat-empty-state"><h3>Transcript unavailable</h3><p>No transcript segments were returned for this video.</p></div>
                : <><div className="view-intro"><h3>The full conversation, in context</h3><p>{processedVideo.transcript.length} segments. Select a timestamp to play that moment.</p></div>
                  <div className="transcript-list">{processedVideo.transcript.map((segment, index) => <div className="transcript-segment" key={`${segment.start_seconds}-${index}`}>
                    <a href={`https://www.youtube.com/watch?v=${video.id}&t=${Math.floor(segment.start_seconds)}s`} target="_blank" rel="noopener noreferrer"
                      aria-label={`Play at ${formatTimestamp(segment.start_seconds)}${isMock ? "; simulated timestamp" : ""}`}
                      onClick={(event) => { if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return; event.preventDefault(); playAtTimestamp(segment.start_seconds); }}>
                      {formatTimestamp(segment.start_seconds)}
                    </a><p>{segment.text}</p>
                  </div>)}</div></>}
            </div>

            <div id="summary-view" role="tabpanel" aria-labelledby="summary-tab" className="summary-view" hidden={activeTab !== "summary"} tabIndex={0} aria-busy={summaryLoading}>
              {!video ? <div className="chat-empty-state"><span className="chat-symbol"><Icon name="layers" size={28} /></span><h3>The big picture</h3><p>Analyse a video to generate its overview and key takeaways.</p></div>
                : summaryLoading ? <div className="summary-loading" role="status"><span className="chat-loading-spinner" aria-hidden="true" /><h3>Putting the ideas together…</h3><p>Preparing an overview of the full video.</p></div>
                : summaryError ? <div className="summary-error"><h3>Let’s try that again</h3><p className="error-text" role="alert">{summaryError}</p><button type="button" className="secondary-button" onClick={() => void loadSummary()}>Retry summary</button></div>
                : summary ? <><div className="view-intro"><span className="summary-symbol"><Icon name="layers" size={20} /></span><h3>Your video, at a glance</h3><p>An overview of the full video and the ideas to take away.</p></div><AnswerText text={summary.answer} />{sources(summary.sources)}<p className="summary-footnote">Generated from the video transcript. Review the sources for context.</p></>
                : <div className="chat-empty-state"><h3>Your video, at a glance</h3><button type="button" className="secondary-button" disabled={isVideoLoading} onClick={() => void loadSummary()}>Generate summary</button></div>}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;
