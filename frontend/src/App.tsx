import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api/client";
import { ChatPanel } from "./components/chat/ChatPanel";
import { TaskWorkspace } from "./components/tasks/TaskWorkspace";

type Tab = "assistant" | "tasks";

function StatusDot() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const [label, color] = isError
    ? ["Offline", "bg-red-500"]
    : data && !data.assistant_configured
      ? ["Assistant not set up", "bg-amber-500"]
      : ["Ready", "bg-emerald-500"];
  return (
    <span className="flex items-center gap-2 text-xs text-slate-500">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("assistant");
  const pane = (t: Tab) => (tab === t ? "flex" : "hidden") + " lg:flex";

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
        <h1 className="text-sm font-semibold tracking-tight text-slate-900">Task Manager</h1>
        <StatusDot />
      </header>

      <nav className="flex shrink-0 gap-1 border-b border-slate-200 bg-white px-3 py-2 lg:hidden" aria-label="Sections">
        {(["assistant", "tasks"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-current={tab === t}
            className={`flex-1 rounded-lg px-3 py-1.5 text-sm font-medium capitalize ${
              tab === t ? "bg-accent-soft text-accent-strong" : "text-slate-500"
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      <main className="grid min-h-0 flex-1 lg:grid-cols-[minmax(360px,440px)_1fr]">
        <div className={`${pane("assistant")} min-h-0 flex-col border-slate-200 lg:border-r`}>
          <ChatPanel />
        </div>
        <div className={`${pane("tasks")} min-h-0 flex-col bg-slate-50`}>
          <TaskWorkspace />
        </div>
      </main>
    </div>
  );
}
