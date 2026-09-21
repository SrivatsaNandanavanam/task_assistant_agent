import { useEffect, useState } from "react";
import { useTaskActions, useTasks } from "../../hooks/useTasks";
import type { Task, TaskFilters as Filters } from "../../types";
import { DeleteConfirmationDialog } from "../chat/DeleteConfirmationDialog";
import { TaskCard } from "./TaskCard";
import { TaskDialog, type TaskFormValues } from "./TaskDialog";
import { TaskFilters } from "./TaskFilters";
import { TaskMetricsStrip } from "./TaskMetricsStrip";
import { NoticeToast, TaskEmptyState, TaskError, TaskSkeleton, type Notice } from "./TaskStates";

export function TaskWorkspace() {
  const [filters, setFilters] = useState<Filters>({ q: "" });
  const { data: tasks, isLoading, isError, refetch } = useTasks(filters);
  const actions = useTaskActions();
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const [deleting, setDeleting] = useState<Task | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [togglingId, setTogglingId] = useState<number | null>(null);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), notice.kind === "error" ? 8000 : 3500);
    return () => clearTimeout(t);
  }, [notice]);

  // Complete <-> reopen. The list only changes after the server confirms (queries are
  // invalidated on success); on failure nothing changes and an error is shown.
  const toggle = (task: Task) => {
    const completing = task.status !== "completed";
    setTogglingId(task.id);
    (completing ? actions.complete : actions.reopen).mutate(task.id, {
      onSuccess: () =>
        setNotice({ kind: "success", text: completing ? `Task #${task.id} marked complete.` : `Task #${task.id} reopened.` }),
      onError: (e: Error) =>
        setNotice({ kind: "error", text: `Couldn't ${completing ? "complete" : "reopen"} task #${task.id}. ${e.message}` }),
      onSettled: () => setTogglingId(null),
    });
  };

  const filtered = !!(filters.q || filters.status || filters.priority);

  const submit = (v: TaskFormValues) => {
    setFormError(null);
    const opts = {
      onSuccess: () => setEditing(null),
      onError: (e: Error) => setFormError(e.message),
    };
    if (editing === "new") actions.create.mutate(v, opts);
    else if (editing) actions.update.mutate({ id: editing.id, body: { ...v, due_at: v.due_at ?? undefined } }, opts);
  };

  return (
    <section aria-label="Tasks" className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Tasks</h2>
          <button
            onClick={() => {
              setFormError(null);
              setEditing("new");
            }}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            + New task
          </button>
        </div>
        <TaskMetricsStrip />
        <TaskFilters filters={filters} onChange={setFilters} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <TaskSkeleton />
        ) : isError ? (
          <TaskError onRetry={() => refetch()} />
        ) : tasks && tasks.length > 0 ? (
          <ul className="space-y-2">
            {tasks.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                onToggle={toggle}
                toggling={togglingId === t.id}
                onEdit={(x) => {
                  setFormError(null);
                  setEditing(x);
                }}
                onDelete={setDeleting}
              />
            ))}
          </ul>
        ) : (
          <TaskEmptyState
            filtered={filtered}
            seeding={actions.seed.isPending}
            onSeed={() => actions.seed.mutate()}
            onNew={() => setEditing("new")}
          />
        )}
      </div>

      {notice && <NoticeToast notice={notice} onDismiss={() => setNotice(null)} />}

      {editing && (
        <TaskDialog
          task={editing === "new" ? undefined : editing}
          busy={actions.create.isPending || actions.update.isPending}
          error={formError}
          onClose={() => setEditing(null)}
          onSubmit={submit}
        />
      )}
      {deleting && (
        <DeleteConfirmationDialog
          task={deleting}
          busy={actions.remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => actions.remove.mutate(deleting.id, { onSettled: () => setDeleting(null) })}
        />
      )}
    </section>
  );
}
