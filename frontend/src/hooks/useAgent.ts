import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import type { AgentResponse, ChatMessage, PendingApproval } from "../types";
import { useRefreshTasks } from "./useTasks";

const uid = () => crypto.randomUUID();

const GREETING: ChatMessage = {
  id: "greeting",
  role: "assistant",
  text: "Hi! Tell me what you'd like to do with your tasks — for example, “Create a high priority task to finish the report tomorrow at 5 PM”.",
};

export function useAgent() {
  const threadId = useRef(uid());
  const refresh = useRefreshTasks();
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [pending, setPending] = useState<PendingApproval | null>(null);
  const [busy, setBusy] = useState(false);

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
        handle(await api.sendMessage(threadId.current, text));
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [handle, fail],
  );

  const resolveApproval = useCallback(
    async (approved: boolean) => {
      setBusy(true);
      try {
        handle(await api.resume(threadId.current, approved));
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [handle, fail],
  );

  return { messages, pending, busy, send, resolveApproval };
}
