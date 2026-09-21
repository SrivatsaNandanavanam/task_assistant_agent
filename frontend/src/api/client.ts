import type { AgentResponse, StoredMessage, Task, TaskFilters, TaskMetrics } from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

/**
 * Normalises VITE_API_BASE_URL into a bare origin such as "https://backend.example.com".
 * Empty (the default) means "same origin": in local development the Vite dev server proxies /api to the
 * backend. Forgiving of the common slips: surrounding spaces, a trailing "/", a trailing "/api" (paths
 * below already start with /api) and a missing "https://" (a scheme-less value would be treated by the
 * browser as a path relative to the frontend's own domain).
 */
export function normalizeApiBase(raw: string | undefined): string {
  let base = (raw ?? "").trim();
  if (!base) return "";
  if (!/^https?:\/\//i.test(base)) base = `https://${base}`;
  return base.replace(/\/+$/, "").replace(/\/api$/i, "");
}

/** Full URL for an API path (paths start with /api). Set at build time: this reads a Vite env variable. */
export function apiUrl(path: string, base: string | undefined = import.meta.env.VITE_API_BASE_URL): string {
  return `${normalizeApiBase(base)}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
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
  getMessages: (thread_id: string, signal?: AbortSignal) =>
    request<StoredMessage[]>(`/api/conversations/${encodeURIComponent(thread_id)}/messages?limit=50`, { signal }),
  resume: (thread_id: string, approved: boolean) =>
    request<AgentResponse>("/api/agent/resume", {
      method: "POST",
      body: JSON.stringify({ thread_id, approved }),
    }),
};
