import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { getThreadId, toChatMessages } from "../lib/conversation";
import type { AgentResponse, ChatMessage, PendingApproval } from "../types";
import { useRefreshTasks } from "./useTasks";

const uid = () => crypto.randomUUID();

/** Give up on loading saved messages after this long, so a slow server can't block the chat. */
const HISTORY_TIMEOUT_MS = 10_000;

const GREETING: ChatMessage = {
  id: "greeting",
  role: "assistant",
  text: "Hi! Tell me what you'd like to do with your tasks — for example, “Create a high priority task to finish the report tomorrow at 5 PM”.",
};

export type HistoryState = "loading" | "ready" | "failed";

export function useAgent() {
  const [threadId] = useState(getThreadId); // persisted in localStorage: the chat survives a refresh
  const refresh = useRefreshTasks();
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [pending, setPending] = useState<PendingApproval | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<HistoryState>("loading");

  // Load the saved conversation once. Nothing can be sent until this settles (see ChatPanel), so the
  // loaded history can never collide with, or duplicate, a message sent in this session.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HISTORY_TIMEOUT_MS);
    api
      .getMessages(threadId, controller.signal)
      .then((stored) => {
        if (cancelled) return;
        setMessages([GREETING, ...toChatMessages(stored)]);
        setHistory("ready");
      })
      .catch(() => {
        if (!cancelled) setHistory("failed"); // chat still works, just without earlier messages
      })
      .finally(() => clearTimeout(timer));
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [threadId]);

  const handle = useCallback(
    (res: AgentResponse) => {
      setMessages((m) => [
        ...m,
        { id: uid(), role: "assistant", text: res.reply, steps: res.steps, failed: res.status === "error" },
      ]);
      setPending(res.status === "awaiting_approval" ? res.pending_approval : null);
      void refresh();
    },
    [refresh],
  );

  const fail = useCallback((e: unknown) => {
    const text = e instanceof Error ? e.message : "Something went wrong. Your tasks were not changed.";
    setMessages((m) => [...m, { id: uid(), role: "assistant", text, failed: true }]);
    setPending(null);
  }, []);

  const send = useCallback(
    async (text: string) => {
      setMessages((m) => [...m, { id: uid(), role: "user", text }]);
      setBusy(true);
      try {
        handle(await api.sendMessage(threadId, text));
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [threadId, handle, fail],
  );

  const resolveApproval = useCallback(
    async (approved: boolean) => {
      setBusy(true);
      try {
        handle(await api.resume(threadId, approved));
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [threadId, handle, fail],
  );

  return { messages, pending, busy, history, send, resolveApproval };
}
