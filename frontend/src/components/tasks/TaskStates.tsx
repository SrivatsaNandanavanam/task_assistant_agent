export function TaskSkeleton() {
  return (
    <ul className="space-y-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <li key={i} className="h-[76px] animate-pulse rounded-xl border border-slate-200 bg-white" />
      ))}
    </ul>
  );
}

interface EmptyProps {
  filtered: boolean;
  onSeed: () => void;
  seeding: boolean;
  onNew: () => void;
}

export function TaskEmptyState({ filtered, onSeed, seeding, onNew }: EmptyProps) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-800">{filtered ? "No matching tasks" : "No tasks yet"}</p>
      <p className="mt-1 text-sm text-slate-500">
        {filtered ? "Try a different search or filter." : "Ask the assistant to create one, or add it yourself."}
      </p>
      {!filtered && (
        <div className="mt-4 flex justify-center gap-2">
          <button onClick={onNew} className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-strong">
            New task
          </button>
          <button
            onClick={onSeed}
            disabled={seeding}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Load demo data
          </button>
        </div>
      )}
    </div>
  );
}

export function TaskError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      Couldn't load your tasks.{" "}
      <button onClick={onRetry} className="font-medium underline">
        Try again
      </button>
    </div>
  );
}

export interface Notice {
  kind: "success" | "error";
  text: string;
}

/** Small non-blocking message for the result of a task action. */
export function NoticeToast({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }) {
  const error = notice.kind === "error";
  return (
    <div
      role={error ? "alert" : "status"}
      className={`fixed bottom-4 right-4 z-40 flex max-w-sm items-start gap-3 rounded-lg border px-3.5 py-2.5 text-sm shadow-lg ${
        error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"
      }`}
    >
      <span>{notice.text}</span>
      <button onClick={onDismiss} aria-label="Dismiss" className="ml-auto opacity-60 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}
