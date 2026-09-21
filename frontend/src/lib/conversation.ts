import type { ChatMessage, StoredMessage } from "../types";

const STORAGE_KEY = "taskManager.threadId";

/** Same rule the backend enforces for conversation ids (CONVERSATION_ID_PATTERN). */
export const THREAD_ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/;

export const EXPIRED_CONFIRMATION_NOTE = "This confirmation has expired. Ask again if you still want to delete it.";

/**
 * The conversation id: reused across page loads via localStorage so the chat history survives a refresh.
 * A stored value that doesn't look like a valid id (corrupted or edited) is ignored. If storage is
 * unavailable (private mode, blocked), the id lives only for this page load and the app still works.
 */
export function getThreadId(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null && THREAD_ID_PATTERN.test(saved)) return saved;
  } catch {
    /* storage unavailable: fall through and use an in-memory id */
  }
  const fresh = crypto.randomUUID();
  try {
    localStorage.setItem(STORAGE_KEY, fresh);
  } catch {
    /* not persisted, still usable for this session */
  }
  return fresh;
}

/**
 * Saved messages -> chat bubbles. Content stays plain text (React escapes it).
 *
 * A delete confirmation only exists in the server's memory while the dialog is open, so it can never be
 * restored from history. If the newest saved message is still an unresolved confirmation, say so instead
 * of leaving a "Please confirm" message with nothing to click. Anything saved after it means it was
 * already resolved or superseded.
 */
export function toChatMessages(stored: StoredMessage[]): ChatMessage[] {
  return stored.map((m, i) => ({
    id: `stored-${m.id}`,
    role: m.role,
    text:
      m.status === "awaiting_approval" && i === stored.length - 1
        ? `${m.content}\n\n${EXPIRED_CONFIRMATION_NOTE}`
        : m.content,
    steps: m.steps ?? undefined,
    failed: m.status === "error",
  }));
}
