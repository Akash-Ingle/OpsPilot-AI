import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, isTransientFailure, listScenarios, login } from "./api";

// Build a minimal Response-like object the api client understands.
function makeRes(
  status: number,
  body: unknown,
  { json = true }: { json?: boolean } = {},
): Response {
  const ok = status >= 200 && status < 300;
  return {
    ok,
    status,
    statusText: `HTTP ${status}`,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type"
          ? json
            ? "application/json"
            : "text/html"
          : null,
    },
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response;
}

describe("isTransientFailure", () => {
  it("treats gateway errors as transient", () => {
    expect(isTransientFailure(502, true)).toBe(true);
    expect(isTransientFailure(503, false)).toBe(true);
    expect(isTransientFailure(504, true)).toBe(true);
  });

  it("treats a non-JSON 500 (proxy cold start) as transient", () => {
    expect(isTransientFailure(500, false)).toBe(true);
  });

  it("treats a JSON 500 (real app error) as non-transient", () => {
    expect(isTransientFailure(500, true)).toBe(false);
  });

  it("treats 4xx as non-transient", () => {
    expect(isTransientFailure(400, false)).toBe(false);
    expect(isTransientFailure(404, true)).toBe(false);
  });
});

describe("request()", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("parses a successful JSON response", async () => {
    const user = { id: 1, email: "a@b.com" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeRes(200, user)),
    );
    await expect(login("a@b.com", "pw")).resolves.toEqual(user);
  });

  it("throws an ApiError carrying the backend detail on a 4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeRes(401, { detail: "Invalid credentials." })),
    );
    await expect(login("a@b.com", "bad")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Invalid credentials.",
    });
  });
});

describe("transient retry", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("retries an idempotent GET through a transient failure", async () => {
    const scenarios = [{ name: "database_failure" }];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeRes(503, "waking up", { json: false }))
      .mockResolvedValueOnce(makeRes(200, scenarios));
    vi.stubGlobal("fetch", fetchMock);

    const promise = listScenarios();
    // Drive the backoff sleep (first delay is 3000ms) to completion.
    await vi.advanceTimersByTimeAsync(3000);

    await expect(promise).resolves.toEqual(scenarios);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

it("exposes ApiError as an Error subclass", () => {
  const err = new ApiError("boom", 500, "/x", null);
  expect(err).toBeInstanceOf(Error);
  expect(err.status).toBe(500);
});
