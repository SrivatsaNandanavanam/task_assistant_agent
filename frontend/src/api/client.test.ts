import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiUrl, normalizeApiBase } from "./client";

const BACKEND = "https://task-assistant-back-agent-un9x.vercel.app";

describe("normalizeApiBase", () => {
  it.each([
    [undefined, ""],
    ["", ""],
    ["   ", ""],
    [BACKEND, BACKEND],
    [`${BACKEND}/`, BACKEND], // trailing slash
    [`${BACKEND}///`, BACKEND],
    [`  ${BACKEND}  `, BACKEND], // stray whitespace from copy/paste
    [`${BACKEND}/api`, BACKEND], // paths already start with /api: avoid /api/api
    [`${BACKEND}/api/`, BACKEND],
    ["task-assistant-back-agent-un9x.vercel.app", BACKEND], // no scheme would become a relative URL
    ["http://localhost:8000", "http://localhost:8000"], // local backend keeps http
    ["HTTPS://Example.com", "HTTPS://Example.com"], // scheme check is case-insensitive
  ])("normalizes %j to %j", (raw, expected) => {
    expect(normalizeApiBase(raw)).toBe(expected);
  });
});

describe("apiUrl", () => {
  it("is the plain relative path when no base is configured (local dev + Vite proxy)", () => {
    expect(apiUrl("/api/health", undefined)).toBe("/api/health");
    expect(apiUrl("/api/health", "")).toBe("/api/health");
  });

  it("prefixes the backend origin without doubling slashes or /api", () => {
    for (const base of [BACKEND, `${BACKEND}/`, `${BACKEND}/api`]) {
      expect(apiUrl("/api/tasks?status=pending", base)).toBe(`${BACKEND}/api/tasks?status=pending`);
    }
  });
});

describe("every API call goes through the configured base URL", () => {
  let urls: string[];

  beforeEach(() => {
    urls = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        urls.push(String(input));
        return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  /** Calls every function on `api`, so a newly added endpoint is covered automatically. */
  async function callEveryEndpoint() {
    const calls: Record<string, () => Promise<unknown>> = {
      health: () => api.health(),
      listTasks: () => api.listTasks({ q: "api", status: "pending", priority: "high" }),
      metrics: () => api.metrics(),
      createTask: () => api.createTask({ title: "t" }),
      updateTask: () => api.updateTask(7, { title: "t" }),
      completeTask: () => api.completeTask(7),
      reopenTask: () => api.reopenTask(7),
      deleteTask: () => api.deleteTask(7),
      seed: () => api.seed(),
      sendMessage: () => api.sendMessage("thread-1", "hi"),
      getMessages: () => api.getMessages("thread-1"),
      resume: () => api.resume("thread-1", true),
    };
    // fails loudly if someone adds an endpoint to `api` without adding it here
    expect(Object.keys(calls).sort()).toEqual(Object.keys(api).sort());
    for (const call of Object.values(calls)) await call();
  }

  it("sends every request to the backend origin when VITE_API_BASE_URL is set", async () => {
    vi.stubEnv("VITE_API_BASE_URL", `${BACKEND}/`);
    await callEveryEndpoint();

    expect(urls).toHaveLength(12);
    for (const url of urls) {
      expect(url.startsWith(`${BACKEND}/api/`)).toBe(true); // right host, single /api prefix
      expect(url).not.toMatch(/\/api\/api\//);
      expect(url.slice(BACKEND.length)).not.toMatch(/\/\//); // no doubled slashes in the path
    }
    expect(urls).toContain(`${BACKEND}/api/health`);
    expect(urls).toContain(`${BACKEND}/api/tasks/metrics`);
    expect(urls).toContain(`${BACKEND}/api/agent/messages`);
    expect(urls).toContain(`${BACKEND}/api/conversations/thread-1/messages?limit=50`);
  });

  it("keeps relative /api URLs when the variable is empty, so the Vite dev proxy still works", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    await callEveryEndpoint();
    expect(urls).toHaveLength(12);
    for (const url of urls) expect(url.startsWith("/api/")).toBe(true);
  });

  it("still reports a network failure as 'Can't reach the server'", async () => {
    vi.stubEnv("VITE_API_BASE_URL", BACKEND);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.health()).rejects.toMatchObject({ status: 0, message: expect.stringContaining("Can't reach the server") });
  });
});

describe("guard against bypassing the client", () => {
  it("api/client.ts is the only source file that calls fetch()", () => {
    const files = import.meta.glob("/src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    expect(Object.keys(files)).toContain("/src/api/client.ts"); // the glob really sees the sources
    const offenders = Object.entries(files)
      .filter(([path, source]) => !/\.test\.tsx?$/.test(path) && !path.endsWith("/src/api/client.ts") && /\bfetch\s*\(/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
