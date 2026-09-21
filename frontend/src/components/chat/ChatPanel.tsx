import { useEffect, useRef } from "react";
import { useAgent } from "../../hooks/useAgent";
import { ChatComposer } from "./ChatComposer";
import { DeleteConfirmationDialog } from "./DeleteConfirmationDialog";
import { MessageBubble } from "./MessageBubble";

const SUGGESTIONS = ["Show my open tasks", "Create a task to review the report tomorrow at 5 PM", "Find tasks about API"];

export function ChatPanel() {
  const { messages, pending, busy, history, send, resolveApproval } = useAgent();
  const endRef = useRef<HTMLDivElement>(null);

  // Jump straight to the newest message once when saved history first appears (a long smooth scroll
  // through a restored conversation is jarring); animate only for messages that arrive afterwards.
  const restored = useRef(false);
  useEffect(() => {
    const jump = history !== "loading" && !restored.current;
    if (history !== "loading") restored.current = true;
    endRef.current?.scrollIntoView({ behavior: jump ? "auto" : "smooth", block: "end" });
  }, [messages, busy, history]);

  return (
    <section aria-label="Assistant" className="flex h-full min-h-0 flex-col bg-slate-50">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
        {history === "loading" && (
          <div className="px-1 text-xs text-slate-400" role="status">
            Loading conversation…
          </div>
        )}
        {history === "failed" && (
          <div className="px-1 text-xs text-slate-400" role="status">
            Earlier messages couldn't be loaded.
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {messages.length === 1 && history !== "loading" && (
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                disabled={busy}
                className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:border-accent hover:text-accent"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-2 px-1 text-xs text-slate-400" role="status">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
            Working on it…
          </div>
        )}
        <div ref={endRef} />
      </div>
      <ChatComposer disabled={busy || !!pending || history === "loading"} onSend={send} />
      {pending && (
        <DeleteConfirmationDialog
          task={pending.task}
          busy={busy}
          onCancel={() => resolveApproval(false)}
          onConfirm={() => resolveApproval(true)}
        />
      )}
    </section>
  );
}
