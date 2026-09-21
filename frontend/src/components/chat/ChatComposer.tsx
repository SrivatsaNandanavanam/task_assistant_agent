import { useState } from "react";

const MAX = 1000;

export function ChatComposer({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");

  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
  };

  return (
    <form
      className="flex items-end gap-2 border-t border-slate-200 bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="chat-input" className="sr-only">
        Message the assistant
      </label>
      <textarea
        id="chat-input"
        rows={1}
        value={text}
        maxLength={MAX}
        placeholder="Ask the assistant…"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        className="max-h-32 min-h-[40px] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="h-10 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
      >
        Send
      </button>
    </form>
  );
}
