import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import { ApiError, requestJson } from "../src/services/http.ts";

afterEach(() => mock.restoreAll());

function waitForAbort(signal) {
  return new Promise((_, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
}

test("returns JSON and forwards request options", async () => {
  const fetch = mock.method(globalThis, "fetch", async () => Response.json({ mode: "real" }));
  assert.deepEqual(await requestJson("/api/videos/process", { method: "POST", body: "{}" }), { mode: "real" });
  assert.equal(fetch.mock.calls[0].arguments[1].method, "POST");
  assert.equal(fetch.mock.calls[0].arguments[1].body, "{}");
});

test("preserves structured backend errors for unprepared videos", async () => {
  mock.method(globalThis, "fetch", async () => Response.json({
    error: { code: "TRANSCRIPT_NOT_CACHED", message: "This video has not been prepared yet." },
  }, { status: 404 }));
  await assert.rejects(requestJson("/video"), (error) =>
    error instanceof ApiError && error.status === 404 &&
    error.code === "TRANSCRIPT_NOT_CACHED" && error.message === "This video has not been prepared yet.");
});

test("handles a non-JSON server failure", async () => {
  mock.method(globalThis, "fetch", async () => new Response("Unavailable", { status: 503 }));
  await assert.rejects(requestJson("/video"), { code: "REQUEST_FAILED", status: 503 });
});

test("reports network failure", async () => {
  mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(requestJson("/video"), { code: "NETWORK_ERROR", status: 0 });
});

test("a stalled backend times out without cancelling the UI's signal", async () => {
  const caller = new AbortController();
  mock.method(globalThis, "fetch", (_, { signal }) => waitForAbort(signal));
  await assert.rejects(requestJson("/video", { signal: caller.signal }, 15), { code: "REQUEST_TIMEOUT" });
  assert.equal(caller.signal.aborted, false);
});

for (const status of [200, 503]) {
  test(`the timeout covers a stalled ${status} response body`, async () => {
    mock.method(globalThis, "fetch", async (_, { signal }) => ({
      ok: status === 200, status, json: () => waitForAbort(signal),
    }));
    await assert.rejects(requestJson("/video", {}, 15), { code: "REQUEST_TIMEOUT" });
  });
}

test("caller cancellation stays an AbortError, not a timeout or network error", async () => {
  const caller = new AbortController();
  mock.method(globalThis, "fetch", (_, { signal }) => waitForAbort(signal));
  const pending = requestJson("/video", { signal: caller.signal }, 500);
  caller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("a caller that was already cancelled stays cancelled", async () => {
  const caller = new AbortController();
  caller.abort();
  mock.method(globalThis, "fetch", (_, { signal }) => waitForAbort(signal));
  await assert.rejects(requestJson("/video", { signal: caller.signal }), { name: "AbortError" });
});

test("successful requests clean up their timeout and cancellation listener", async () => {
  const caller = new AbortController();
  const remove = mock.method(caller.signal, "removeEventListener");
  let requestSignal;
  mock.method(globalThis, "fetch", async (_, { signal }) => {
    requestSignal = signal;
    return Response.json({ ok: true });
  });
  await requestJson("/video", { signal: caller.signal }, 15);
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(requestSignal.aborted, false);
  assert.equal(remove.mock.callCount(), 1);
  caller.abort();
  assert.equal(requestSignal.aborted, false);
});
