import type {
  ChatRequest,
  ChatResponse,
  ErrorResponse,
  HealthResponse,
  ProcessVideoResponse,
} from "../types/api";


const API_BASE_URL = (
  import.meta.env.VITE_BACKEND_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, options);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }

    throw new ApiError(
      "Cannot reach the backend. Check that it is running and allows this frontend address.",
      "NETWORK_ERROR",
      0,
    );
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}). Please try again.`;
    let code = "REQUEST_FAILED";

    try {
      const body = (await response.json()) as ErrorResponse;

      if (typeof body.error?.message === "string") {
        message = body.error.message;
      }

      if (typeof body.error?.code === "string") {
        code = body.error.code;
      }
    } catch {
      // Keep the fallback message if the server did not return JSON.
    }

    throw new ApiError(message, code, response.status);
  }

  return response.json() as Promise<T>;
}

export function checkHealth(signal?: AbortSignal) {
  return request<HealthResponse>("/api/health", { signal });
}

export function processVideo(url: string, signal?: AbortSignal) {
  return request<ProcessVideoResponse>("/api/videos/process", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
    signal,
  });
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