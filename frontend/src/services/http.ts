import type { ErrorResponse } from "../types/api";

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

export async function requestJson<T>(
  url: string,
  options: RequestInit = {},
  timeoutMs = 15_000,
): Promise<T> {
  // Keep the caller's cancellation separate: the UI silently ignores requests
  // cancelled on reset/unmount, but must display internal timeout errors.
  const controller = new AbortController();
  const callerSignal = options.signal;
  const cancel = () => controller.abort(callerSignal?.reason);
  let timedOut = false;

  if (callerSignal?.aborted) {
    cancel();
  } else {
    callerSignal?.addEventListener("abort", cancel, { once: true });
  }

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = `Request failed (${response.status}). Please try again.`;
      let code = "REQUEST_FAILED";

      try {
        const body = (await response.json()) as ErrorResponse;
        if (typeof body?.error?.message === "string") {
          message = body.error.message;
        }
        if (typeof body?.error?.code === "string") {
          code = body.error.code;
        }
      } catch (error) {
        // Cancellation during an error body must still reach the timeout handler.
        if (controller.signal.aborted) throw error;
      }

      throw new ApiError(message, code, response.status);
    }

    // Await the body before clearing the timer; headers alone aren't completion.
    return await response.json() as T;
  } catch (error) {
    if (callerSignal?.aborted) throw callerSignal.reason;
    if (timedOut) {
      throw new ApiError(
        "The backend took too long to respond. Please try again. If this continues, restart the backend.",
        "REQUEST_TIMEOUT",
        0,
      );
    }
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") throw error;

    throw new ApiError(
      "Cannot reach the backend. Check that it is running and allows this frontend address.",
      "NETWORK_ERROR",
      0,
    );
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", cancel);
  }
}
