import type { TaskFilters as Filters } from "../../types";

const CHIPS: { label: string; match: (f: Filters) => boolean; apply: Partial<Filters> }[] = [
  { label: "All", match: (f) => !f.status && !f.priority, apply: { status: undefined, priority: undefined } },
  { label: "Open", match: (f) => f.status === "pending" && !f.priority, apply: { status: "pending", priority: undefined } },
  {
    label: "Completed",
    match: (f) => f.status === "completed" && !f.priority,
    apply: { status: "completed", priority: undefined },
  },
  {
    label: "High priority",
    match: (f) => f.priority === "high" && !f.status,
    apply: { status: undefined, priority: "high" },
  },
];

export function TaskFilters({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  return (
    <div className="space-y-2.5">
      <div>
        <label htmlFor="task-search" className="sr-only">
          Search tasks
        </label>
        <input
          id="task-search"
          type="search"
          value={filters.q}
          onChange={(e) => onChange({ ...filters, q: e.target.value })}
          placeholder="Search tasks…"
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400"
        />
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter tasks">
        {CHIPS.map((c) => {
          const active = c.match(filters);
          return (
            <button
              key={c.label}
              aria-pressed={active}
              onClick={() => onChange({ ...filters, ...c.apply })}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                active
                  ? "border-accent bg-accent-soft text-accent-strong"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
              }`}
            >
              {c.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
