import { formatDue } from "../../lib/dates";
import type { Priority, Task } from "../../types";

const PRIORITY_CLS: Record<Priority, string> = {
  high: "bg-red-50 text-red-700 ring-red-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-slate-100 text-slate-600 ring-slate-200",
};

interface Props {
  task: Task;
  onToggle: (t: Task) => void;
  toggling?: boolean;
  onEdit: (t: Task) => void;
  onDelete: (t: Task) => void;
}

export function TaskCard({ task, onToggle, toggling, onEdit, onDelete }: Props) {
  const done = task.status === "completed";
  const overdue = !done && task.due_at !== null && new Date(task.due_at) < new Date();
  return (
    <li className="group rounded-xl border border-slate-200 bg-white p-3.5 transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3">
        <button
          role="checkbox"
          aria-checked={done}
          onClick={() => onToggle(task)}
          disabled={toggling}
          aria-label={done ? `Reopen task ${task.id}` : `Mark task ${task.id} complete`}
          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs ${
            done
              ? "border-emerald-500 bg-emerald-500 text-white hover:bg-emerald-600"
              : "border-slate-300 text-transparent hover:border-emerald-500 hover:text-emerald-500"
          }`}
        >
          ✓
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-xs tabular-nums text-slate-400">#{task.id}</span>
            <h3 className={`truncate text-sm font-medium ${done ? "text-slate-400 line-through" : "text-slate-900"}`}>
              {task.title}
            </h3>
          </div>
          {task.description && <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{task.description}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded-full px-2 py-0.5 font-medium uppercase ring-1 ring-inset ${PRIORITY_CLS[task.priority]}`}>
              {task.priority}
            </span>
            <span className="font-medium uppercase text-slate-500">{done ? "Completed" : "Open"}</span>
            {task.due_at && (
              <span className={overdue ? "font-medium text-red-600" : "text-slate-500"}>
                {overdue && "Overdue · "}
                {formatDue(task.due_at)}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 gap-1 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          <button
            onClick={() => onEdit(task)}
            className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(task)}
            className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-red-50 hover:text-red-700"
          >
            Delete
          </button>
        </div>
      </div>
    </li>
  );
}
