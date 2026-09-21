import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EXPIRED_CONFIRMATION_NOTE, THREAD_ID_PATTERN } from "../../lib/conversation";
import type { ReceiptStep, StoredMessage } from "../../types";
import { ChatPanel } from "./ChatPanel";

const KEY = "taskManager.threadId";
const STEPS: ReceiptStep[] = [
  { key: "understand", label: "Understand request", status: "done", detail: "Create a task" },
  { key: "return", label: "Return result", status: "done", detail: null },
];

let nextId = 1;
function stored(
  role: "user" | "assistant",
  content: string,
  status: StoredMessage["status"] = null,
  steps: ReceiptStep[] | null = null,
): StoredMessage {
  return { id: nextId++, role, content, status, steps, created_at: "2026-09-21T10:00:00Z" };
}

/** In-memory server: saved messages per thread, plus a log of every request. */
function fakeBackend(seed: Record<string, StoredMessage[]> = {}) {
  const be = {
    byThread: seed,
    calls: [] as { method: string; url: string; body?: { thread_id: string; message: string } }[],
    historyStatus: 200,
    hold: null as null | Promise<void>,
  };
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      be.calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });

      const history = url.match(/^\/api\/conversations\/([^/?]+)\/messages/);
      if (method === "GET" && history) {
        if (be.hold) await be.hold;
        if (be.historyStatus !== 200) return json({ detail: "Conversation history is temporarily unavailable." }, be.historyStatus);
        return json(be.byThread[decodeURIComponent(history[1])] ?? []);
      }
      if (method === "POST" && url === "/api/agent/messages") {
        const { thread_id, message } = JSON.parse(String(init?.body));
        const reply = "Created task #1.";
        (be.byThread[thread_id] ??= []).push(stored("user", message), stored("assistant", reply, "success", STEPS));
        return json({ thread_id, status: "success", reply, steps: STEPS, pending_approval: null, last_task_id: 1 });
      }
      return json({ detail: "not found" }, 404);
    }),
  );
  return be;
}

const historyCalls = (be: ReturnType<typeof fakeBackend>) => be.calls.filter((c) => c.method === "GET");
const postCalls = (be: ReturnType<typeof fakeBackend>) => be.calls.filter((c) => c.method === "POST");
const threadOf = (url: string) => decodeURIComponent(url.split("/")[3]);

function renderChat() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatPanel />
    </QueryClientProvider>,
  );
}

async function waitUntilLoaded() {
  await waitFor(() => expect(screen.queryByText("Loading conversation…")).toBeNull());
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message the assistant"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  Element.prototype.scrollIntoView = vi.fn(); // not implemented by jsdom
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("thread id", () => {
  it("creates and stores a valid thread id on the first visit, then loads that (empty) conversation", async () => {
    const be = fakeBackend();
    renderChat();

    await screen.findByText("Show my open tasks"); // empty history: greeting + suggestions
    const saved = localStorage.getItem(KEY)!;
    expect(saved).toMatch(THREAD_ID_PATTERN);
    expect(historyCalls(be)).toHaveLength(1);
    expect(historyCalls(be)[0].url).toBe(`/api/conversations/${saved}/messages?limit=50`);
  });

  it("reuses the stored id and never asks for another conversation", async () => {
    localStorage.setItem(KEY, "returning-thread");
    const be = fakeBackend({
      "returning-thread": [stored("user", "mine")],
      "someone-elses-thread": [stored("user", "not mine")],
    });
    renderChat();

    await screen.findByText("mine");
    expect(screen.queryByText("not mine")).toBeNull();
    expect(historyCalls(be).map((c) => threadOf(c.url))).toEqual(["returning-thread"]);
    expect(localStorage.getItem(KEY)).toBe("returning-thread");
  });

  it.each(["bad id!", "x".repeat(101), "<script>alert(1)</script>", ""])(
    "replaces a corrupted stored id (%j) with a fresh valid one",
    async (corrupt) => {
      localStorage.setItem(KEY, corrupt);
      const be = fakeBackend();
      renderChat();

      await waitUntilLoaded();
      const used = threadOf(historyCalls(be)[0].url);
      expect(used).toMatch(THREAD_ID_PATTERN);
      expect(used).not.toBe(corrupt);
      expect(localStorage.getItem(KEY)).toBe(used);
    },
  );

  it("still works when localStorage is unavailable, using one id for the whole session", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const be = fakeBackend();
    renderChat();
    await waitUntilLoaded();

    send("Create a task called demo");
    await screen.findByText("Created task #1.");
    const id = threadOf(historyCalls(be)[0].url);
    expect(id).toMatch(THREAD_ID_PATTERN);
    expect(postCalls(be)[0].body!.thread_id).toBe(id);
  });
});

describe("history hydration", () => {
  it("shows saved messages in order after the greeting, without suggestions", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({
      t1: [stored("user", "Create a task called demo"), stored("assistant", "Created task #1 — demo.", "success", STEPS)],
    });
    renderChat();

    await screen.findByText(/Created task #1 — demo\./);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Hi! Tell me")).toBeLessThan(text.indexOf("Create a task called demo"));
    expect(text.indexOf("Create a task called demo")).toBeLessThan(text.indexOf("Created task #1 — demo."));
    expect(screen.queryByText("Show my open tasks")).toBeNull();
    expect(screen.getAllByText("Activity")).toHaveLength(1); // saved workflow steps come back too
  });

  it("marks saved error replies as failed", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({ t1: [stored("user", "x"), stored("assistant", "I couldn't interpret that request right now.", "error")] });
    renderChat();

    const bubble = await screen.findByText(/couldn't interpret that request/);
    expect(bubble.className).toContain("red");
  });

  it("disables sending while history loads, keeps what was typed, and then allows it", async () => {
    localStorage.setItem(KEY, "t1");
    const be = fakeBackend({ t1: [stored("user", "earlier message")] });
    let release!: () => void;
    be.hold = new Promise<void>((r) => (release = r));
    renderChat();

    expect(screen.getByText("Loading conversation…")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Message the assistant"), { target: { value: "typed early" } });
    const button = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.keyDown(screen.getByLabelText("Message the assistant"), { key: "Enter" });
    expect(postCalls(be)).toHaveLength(0); // Enter cannot bypass the lock either

    release();
    await screen.findByText("earlier message");
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Created task #1.");
    expect(postCalls(be)[0].body!.message).toBe("typed early");
  });

  it("falls back to a working chat with a notice when history cannot be loaded", async () => {
    localStorage.setItem(KEY, "t1");
    const be = fakeBackend({ t1: [stored("user", "hidden by failure")] });
    be.historyStatus = 503;
    renderChat();

    await screen.findByText("Earlier messages couldn't be loaded.");
    expect(screen.getByText(/Hi! Tell me/)).toBeTruthy();
    expect(screen.queryByText("hidden by failure")).toBeNull();
    expect(document.body.textContent).not.toContain("temporarily unavailable"); // server text is not surfaced

    send("Create a task called demo");
    await screen.findByText("Created task #1.");
    expect(postCalls(be)[0].body!.thread_id).toBe("t1"); // same conversation continues
  });

  it("keeps the conversation across a page reload", async () => {
    const be = fakeBackend();
    const first = renderChat();
    await waitUntilLoaded();
    send("Create a task called demo");
    await screen.findByText("Created task #1.");
    const id = postCalls(be)[0].body!.thread_id;
    first.unmount(); // "reload"

    renderChat();
    await screen.findByText("Create a task called demo");
    expect(screen.getByText(/Created task #1\./)).toBeTruthy();
    expect(historyCalls(be).map((c) => threadOf(c.url))).toEqual([id, id]);
    expect(postCalls(be)).toHaveLength(1); // nothing was re-sent
  });

  it("jumps straight to the newest saved message, then scrolls smoothly for new ones", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({ t1: [stored("user", "a"), stored("assistant", "b", "success")] });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderChat();
    await screen.findByText("b");

    expect(scroll.mock.lastCall![0]).toMatchObject({ behavior: "auto" }); // restored history: instant
    send("c");
    await screen.findByText("Created task #1.");
    expect(scroll.mock.lastCall![0]).toMatchObject({ behavior: "smooth" }); // live messages: animated
  });

  it("does not warn about duplicate keys when live messages follow saved ones", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({ t1: [stored("user", "a"), stored("assistant", "b", "success")] });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    renderChat();
    await screen.findByText("b");
    send("c");
    await screen.findByText("Created task #1.");
    expect(errors).not.toHaveBeenCalled();
  });
});

describe("pending delete confirmations are never restored", () => {
  const ask = () => stored("user", "Delete the deployment task");
  const awaiting = () =>
    stored("assistant", "Delete task #8 — Fix production deployment? Please confirm or cancel.", "awaiting_approval");

  it("marks an unresolved confirmation as expired and opens no dialog", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({ t1: [ask(), awaiting()] });
    renderChat();

    await screen.findByText(new RegExp(EXPIRED_CONFIRMATION_NOTE));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("does not mark a confirmation that was resolved or superseded", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({ t1: [ask(), awaiting(), stored("assistant", "Deletion cancelled.", "cancelled")] });
    renderChat();
    await screen.findByText("Deletion cancelled.");
    expect(screen.queryByText(new RegExp(EXPIRED_CONFIRMATION_NOTE))).toBeNull();
    cleanup();

    localStorage.setItem(KEY, "t2");
    fakeBackend({ t2: [ask(), awaiting(), stored("user", "never mind, show my tasks")] });
    renderChat();
    await screen.findByText("never mind, show my tasks");
    expect(screen.queryByText(new RegExp(EXPIRED_CONFIRMATION_NOTE))).toBeNull();
  });
});

describe("saved content is untrusted", () => {
  it("renders stored HTML as plain text", async () => {
    localStorage.setItem(KEY, "t1");
    fakeBackend({
      t1: [stored("user", '<img src=x onerror="window.__pwned = 1">'), stored("assistant", "<b>bold?</b>", "success")],
    });
    const { container } = renderChat();

    await screen.findByText("<b>bold?</b>");
    expect(screen.getByText('<img src=x onerror="window.__pwned = 1">')).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });
});
