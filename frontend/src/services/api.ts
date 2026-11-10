import type {
  ChatRequest,
  ChatResponse,
  HealthResponse,
  ProcessVideoResponse,
} from "../types/api";
import { requestJson } from "./http";
export { ApiError } from "./http";

const API_BASE_URL = (
  import.meta.env.VITE_BACKEND_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

async function request<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs?: number,
): Promise<T> {
  return requestJson<T>(`${API_BASE_URL}${path}`, options, timeoutMs);
}

export function checkHealth(signal?: AbortSignal) {
  return request<HealthResponse>("/api/health", { signal });
}

export function processVideo(url: string, signal?: AbortSignal) {
  // A local cache miss includes caption retrieval and a confirmed database write.
  return request<ProcessVideoResponse>("/api/videos/process", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
    signal,
  }, 180_000);
}

export function askQuestion(
  payload: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request<ChatResponse>(
    "/api/chat/ask",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal,
    },
    90_000,
  );
}

export type TranscriptionResponse = {
  text: string;
  language?: string | null;
  model: string;
};

export function transcribeAudio(audio: Blob, signal?: AbortSignal) {
  const mime = audio.type.split(";")[0].toLowerCase();
  const extensions: Record<string, string> = {
    "audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg",
    "audio/wav": "wav", "audio/mpeg": "mp3",
  };
  const extension = extensions[mime];
  if (!extension) throw new Error("This recording format is unsupported. Try Chrome or Edge.");
  const form = new FormData();
  form.append("file", audio, `question.${extension}`);
  // Let the browser set the multipart boundary.
  return request<TranscriptionResponse>("/api/audio/transcribe", {
    method: "POST", body: form, signal,
  }, 90_000);
}
