import type {
  ChatRequest,
  ChatResponse,
  HealthResponse,
  ProcessVideoResponse,
} from "../types/api";
import { requestJson } from "./http";
export { ApiError } from "./http";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
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
  }, 60_000);
}

export function askQuestion(
  payload: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });
}
