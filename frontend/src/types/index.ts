export type Priority = "low" | "medium" | "high";
export type Status = "pending" | "completed";

export interface Task {
  id: number;
  title: string;
  description: string | null;
  status: Status;
  priority: Priority;
  due_at: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskMetrics {
  total: number;
  open: number;
  completed: number;
  overdue: number;
}

export interface TaskFilters {
  q: string;
  status?: Status;
  priority?: Priority;
}

export interface ReceiptStep {
  key: string;
  label: string;
  status: "done" | "pending" | "waiting" | "failed" | "skipped";
  detail: string | null;
}

export interface PendingApproval {
  action: "delete_task";
  task: { id: number; title: string; priority: Priority };
  message: string;
}

export interface AgentResponse {
  thread_id: string;
  status: "success" | "clarify" | "unsupported" | "cancelled" | "error" | "awaiting_approval";
  reply: string;
  steps: ReceiptStep[];
  pending_approval: PendingApproval | null;
  last_task_id: number | null;
}

/** A saved chat message as returned by GET /api/conversations/{thread_id}/messages. */
export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: AgentResponse["status"] | null;
  steps: ReceiptStep[] | null;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps?: ReceiptStep[];
  failed?: boolean;
}
