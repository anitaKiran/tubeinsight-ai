import { useEffect, useRef, useState } from "react";

import type { FormEvent } from "react";

type AudioRecorderProps = {
  question: string;
  onQuestionChange: (text: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  disabled: boolean;
  sending: boolean;
  errorId?: string;
};

function Icon({ kind }: { kind: "mic" | "send" | "close" | "stop" }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {kind === "mic" && <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" /></>}
      {kind === "send" && <path d="M12 19V5m-6 6 6-6 6 6" />}
      {kind === "close" && <path d="m6 6 12 12M18 6 6 18" />}
      {kind === "stop" && <rect x="6" y="6" width="12" height="12" rx="2" />}
    </svg>
  );
}

type RecordingStatus = "idle" | "requesting" | "recording" | "stopping";

function AudioRecorder({ question, onQuestionChange, onSubmit, disabled, sending, errorId }: AudioRecorderProps) {
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [audioUrl, setAudioUrl] = useState("");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioUrlRef = useRef("");
  const requestIdRef = useRef(0);
  const discardRef = useRef(false);
  const busyRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function releaseMicrophone() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }

  function clearPreview() {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = "";
    }

    setAudioUrl("");
    setSeconds(0);
  }

  useEffect(() => {
    return () => {
      requestIdRef.current += 1;

      const recorder = recorderRef.current;

      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onstop = null;
        recorder.onerror = null;

        if (recorder.state !== "inactive") {
          recorder.stop();
        }
      }

      releaseMicrophone();

      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = "";
      }
    };
  }, []);

  async function startRecording() {
    if (busyRef.current || disabled) return;

    setError("");

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("Audio recording is unavailable in this browser.");
      return;
    }

    busyRef.current = true;
    const requestId = ++requestIdRef.current;
    discardRef.current = false;
    clearPreview();
    setStatus("requesting");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });

      // Permission may arrive after cancellation or leaving this component.
      if (requestId !== requestIdRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = stream;

      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));

      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      recorderRef.current = recorder;
      const chunks: Blob[] = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunks.push(event.data);
        }
      };

      recorder.onerror = () => {
        discardRef.current = true;
        setError("Recording failed. Please try again.");

        if (recorder.state !== "inactive") {
          recorder.stop();
        }

        releaseMicrophone();
        setStatus("stopping");
      };

      recorder.onstop = () => {
        releaseMicrophone();
        recorderRef.current = null;
        busyRef.current = false;
        setStatus("idle");

        if (discardRef.current) return;

        const audio = new Blob(chunks, {
          type: recorder.mimeType || chunks[0]?.type,
        });

        if (audio.size === 0) {
          setError("No audio was recorded. Please try again.");
          return;
        }

        const url = URL.createObjectURL(audio);
        audioUrlRef.current = url;
        setAudioUrl(url);
      };

      recorder.start();
      setStatus("recording");

      const startedAt = Date.now();

      intervalRef.current = setInterval(() => {
        setSeconds(Math.min(60, Math.floor((Date.now() - startedAt) / 1000)));
      }, 250);

      timeoutRef.current = setTimeout(() => {
        if (recorder.state === "recording") {
          setStatus("stopping");
          recorder.stop();
        }
      }, 60_000);
    } catch (recordingError) {
      if (requestId !== requestIdRef.current) return;

      releaseMicrophone();
      busyRef.current = false;
      setStatus("idle");

      const name =
        recordingError instanceof DOMException ? recordingError.name : "";

      setError(
        name === "NotAllowedError"
          ? "Microphone access was denied. Allow it in your browser settings."
          : name === "NotFoundError"
            ? "No microphone was found. Connect one and try again."
            : "Couldn’t start recording. Check your microphone and try again.",
      );
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current;

    if (recorder?.state === "recording") {
      setStatus("stopping");
      recorder.stop();
    }
  }

  function cancelRecording() {
    requestIdRef.current += 1;
    discardRef.current = true;

    const recorder = recorderRef.current;

    if (recorder && recorder.state !== "inactive") {
      setStatus("stopping");
      recorder.stop();
      releaseMicrophone();
    } else {
      releaseMicrophone();
      busyRef.current = false;
      setStatus("idle");
    }

    clearPreview();
    setError("");
  }

  const active = status !== "idle";
  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="voice-composer">
      <form
        className={`voice-composer-bar${active ? " is-recording" : ""}`}
        onSubmit={(event) => {
          if (active || disabled || !question.trim()) {
            event.preventDefault();
            return;
          }
          onSubmit(event);
        }}
      >
        {active ? (
          <>
            <button className="composer-icon" type="button" onClick={cancelRecording}
              disabled={status === "stopping"} aria-label="Cancel recording" title="Cancel recording">
              <Icon kind="close" />
            </button>
            <div className="recording-indicator" aria-hidden="true">
              <span className="recording-dot" />
              <span className="recording-time">{time}</span>
            </div>
            <div className={`recording-bars${status !== "recording" ? " is-paused" : ""}`} aria-hidden="true">
              {Array.from({ length: 18 }, (_, index) => (
                <span key={index} style={{ height: `${10 + ((index * 13) % 25)}px`, animationDelay: `${index * 0.07}s` }} />
              ))}
            </div>
            <button className="composer-icon composer-stop" type="button" onClick={stopRecording}
              disabled={status !== "recording"} aria-label="Stop recording" title="Stop recording">
              <Icon kind="stop" />
            </button>
          </>
        ) : (
          <>
            <label className="sr-only" htmlFor="question">Your question</label>
            <input id="question" type="text" placeholder={disabled ? "Chat is currently unavailable" : "Ask about this video…"}
              value={question} onChange={(event) => onQuestionChange(event.target.value)}
              disabled={disabled} aria-describedby={errorId} maxLength={2000} />
            <button className="composer-icon" type="button" onClick={startRecording} disabled={disabled}
              aria-label={audioUrl ? "Record question again" : "Record a question"} title="Record a question">
              <Icon kind="mic" />
            </button>
            <button className="composer-icon composer-send" type="submit" disabled={disabled || !question.trim()}
              aria-label={sending ? "Sending question" : "Send question"} title="Send question">
              <Icon kind="send" />
            </button>
          </>
        )}
      </form>

      <p className="voice-composer-hint" role="status">
        {status === "requesting" ? "Allow microphone access to start recording." :
          status === "recording" ? "Recording… stop when you’re done. Maximum 60 seconds." :
          status === "stopping" ? "Finishing your recording…" :
          sending ? "Preparing your answer…" : "Type a question or tap the microphone to record."}
      </p>

      {audioUrl && (
        <div className="recording-review">
          <div className="recording-review-heading">
            <span className="recording-ready-badge">Recording ready</span>
            <button className="recording-discard" type="button" onClick={clearPreview}>Discard</button>
          </div>
          <audio controls src={audioUrl} aria-label="Recorded question preview" />
          <p>Listen to your recording. Speech-to-text will be available once connected.</p>
        </div>
      )}
      {error && <p className="recording-error" role="alert">{error}</p>}
    </div>
  );
}

export default AudioRecorder;
