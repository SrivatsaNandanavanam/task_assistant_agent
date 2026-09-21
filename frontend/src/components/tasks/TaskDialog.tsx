import { useEffect, useRef, useState } from "react";
import { toLocalInput } from "../../lib/dates";
import type { Priority, Task } from "../../types";

export interface TaskFormValues {
  title: string;
  description: string | null;
  priority: Priority;
  due_at: string | null;
}

interface Props {
  task?: Task;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (v: TaskFormValues) => void;
}

export function TaskDialog({ task, busy, error, onClose, onSubmit }: Props) {
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [priority, setPriority] = useState<Priority>(task?.priority ?? "medium");
  const [due, setDue] = useState(toLocalInput(task?.due_at ?? null));
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const field = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <form
        role="dialog"
        aria-modal="true"
        aria-label={task ? "Edit task" : "New task"}
        className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({
            title: title.trim(),
            description: description.trim() || null,
            priority,
            due_at: due ? new Date(due).toISOString() : null,
          });
        }}
      >
        <h2 className="text-base font-semibold">{task ? `Edit task #${task.id}` : "New task"}</h2>
        <div className="mt-4 space-y-3">
          <label className="block text-sm font-medium text-slate-700">
            Title
            <input
              ref={titleRef}
              required
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className={field}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Description
            <textarea
              rows={3}
              maxLength={2000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className={field}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm font-medium text-slate-700">
              Priority
              <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)} className={field}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Due
              <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className={field} />
            </label>
          </div>
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !title.trim()}
            className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-strong disabled:opacity-50"
          >
            {task ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
