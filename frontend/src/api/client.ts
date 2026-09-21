import type { AgentResponse, Task, TaskFilters, TaskMetrics } from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep generic message */
    }
    throw new ApiError(message, res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  health: () => request<{ status: string; assistant_configured: boolean }>("/api/health"),
  listTasks: (f: TaskFilters) => {
    const p = new URLSearchParams();
    if (f.q.trim()) p.set("q", f.q.trim());
    if (f.status) p.set("status", f.status);
    if (f.priority) p.set("priority", f.priority);
    return request<Task[]>(`/api/tasks?${p}`);
  },
  metrics: () => request<TaskMetrics>("/api/tasks/metrics"),
  createTask: (body: { title: string; description?: string | null; priority?: string; due_at?: string | null }) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
  updateTask: (id: number, body: Record<string, unknown>) =>
    request<Task>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  completeTask: (id: number) => request<Task>(`/api/tasks/${id}/complete`, { method: "POST" }),
  reopenTask: (id: number) => request<Task>(`/api/tasks/${id}/reopen`, { method: "POST" }),
  deleteTask: (id: number) => request<void>(`/api/tasks/${id}`, { method: "DELETE" }),
  seed: () => request<{ created: number }>("/api/tasks/seed", { method: "POST" }),
  sendMessage: (thread_id: string, message: string) =>
    request<AgentResponse>("/api/agent/messages", {
      method: "POST",
      body: JSON.stringify({
        thread_id,
        message,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    }),
  resume: (thread_id: string, approved: boolean) =>
    request<AgentResponse>("/api/agent/resume", {
      method: "POST",
      body: JSON.stringify({ thread_id, approved }),
    }),
};
