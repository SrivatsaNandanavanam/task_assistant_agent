import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "../../types";
import { TaskWorkspace } from "./TaskWorkspace";

const base: Task = {
  id: 1,
  title: "Ship the report",
  description: "Quarterly numbers",
  status: "completed",
  priority: "high",
  due_at: "2030-01-01T12:00:00Z",
  created_at: "2029-12-01T00:00:00Z",
  updated_at: "2029-12-01T00:00:00Z",
  completed_at: "2029-12-02T00:00:00Z",
};

/** Minimal in-memory server behind fetch. `failNext` makes the next POST fail with a 500. */
function fakeServer(initial: Task) {
  const state = { task: { ...initial }, failNext: false, hold: null as null | Promise<void>, posts: [] as string[] };
  const json = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET" && url.startsWith("/api/tasks/metrics")) {
        const done = state.task.status === "completed" ? 1 : 0;
        return json({ total: 1, open: 1 - done, completed: done, overdue: 0 });
      }
      if (method === "GET" && url.startsWith("/api/tasks")) return json([state.task]);
      if (method === "POST") {
        state.posts.push(url);
        if (state.hold) await state.hold;
        if (state.failNext) {
          state.failNext = false;
          return json({ detail: "I couldn't save that change." }, 500);
        }
        if (url.endsWith("/complete")) state.task = { ...state.task, status: "completed", completed_at: "2030-01-01T00:00:00Z" };
        if (url.endsWith("/reopen")) state.task = { ...state.task, status: "pending", completed_at: null };
        return json(state.task);
      }
      return json({ detail: "not found" }, 404);
    }),
  );
  return state;
}

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TaskWorkspace />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(cleanup);

describe("task checkbox toggles complete <-> open", () => {
  it("reopens a completed task and shows a success message after the server confirms", async () => {
    const server = fakeServer(base);
    renderWorkspace();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Reopen task 1" }));

    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining("Task #1 reopened."));
    expect(await screen.findByRole("checkbox", { name: "Mark task 1 complete" })).toBeTruthy();
    expect(server.posts).toEqual(["/api/tasks/1/reopen"]);
    // existing fields are untouched
    expect(screen.getByText("Ship the report")).toBeTruthy();
    expect(screen.getByText("Quarterly numbers")).toBeTruthy();
    expect(screen.getByText("high")).toBeTruthy();
  });

  it("completes an open task, then reopens it again (open -> completed -> open)", async () => {
    const server = fakeServer({ ...base, status: "pending", completed_at: null });
    renderWorkspace();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Mark task 1 complete" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Reopen task 1" }));
    expect(await screen.findByRole("checkbox", { name: "Mark task 1 complete" })).toBeTruthy();
    expect(server.posts).toEqual(["/api/tasks/1/complete", "/api/tasks/1/reopen"]);
  });

  it("keeps showing the old state until the server responds", async () => {
    let release!: () => void;
    const server = fakeServer(base);
    server.hold = new Promise<void>((r) => (release = r));
    renderWorkspace();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Reopen task 1" }));
    await waitFor(() => expect(server.posts).toHaveLength(1));
    // request in flight: no optimistic flip, and the button is locked against double clicks
    const box = screen.getByRole("checkbox", { name: "Reopen task 1" }) as HTMLButtonElement;
    expect(box.disabled).toBe(true);
    expect(screen.queryByRole("checkbox", { name: "Mark task 1 complete" })).toBeNull();

    release();
    expect(await screen.findByRole("checkbox", { name: "Mark task 1 complete" })).toBeTruthy();
  });

  it("after a failed request: shows an error, leaves the task completed, and allows retry", async () => {
    const server = fakeServer(base);
    server.failNext = true;
    renderWorkspace();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Reopen task 1" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Couldn't reopen task #1.");
    expect(alert.textContent).toContain("I couldn't save that change.");
    // UI still reflects the real (unchanged) database state
    const box = (await screen.findByRole("checkbox", { name: "Reopen task 1" })) as HTMLButtonElement;
    expect(box.getAttribute("aria-checked")).toBe("true");
    expect(box.disabled).toBe(false);
    expect(screen.queryByText(/reopened/)).toBeNull();

    fireEvent.click(box); // retry succeeds
    expect(await screen.findByRole("checkbox", { name: "Mark task 1 complete" })).toBeTruthy();
    expect(server.posts).toEqual(["/api/tasks/1/reopen", "/api/tasks/1/reopen"]);
  });
});
