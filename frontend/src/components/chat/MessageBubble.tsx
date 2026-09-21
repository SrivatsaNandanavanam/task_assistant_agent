import type { ChatMessage } from "../../types";
import { AgentActivity } from "./AgentActivity";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const mine = message.role === "user";
  return (
    <div className={`flex flex-col ${mine ? "items-end" : "items-start"}`}>
      <div className="mb-1 px-1 text-xs font-medium text-slate-400">{mine ? "You" : "Assistant"}</div>
      <div
        className={`max-w-[92%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
          mine
            ? "rounded-br-md bg-accent text-white"
            : message.failed
              ? "rounded-bl-md border border-red-200 bg-red-50 text-red-900"
              : "rounded-bl-md border border-slate-200 bg-white text-slate-800"
        }`}
      >
        {message.text}
        {message.steps && <AgentActivity steps={message.steps} failed={message.failed} />}
      </div>
    </div>
  );
}
