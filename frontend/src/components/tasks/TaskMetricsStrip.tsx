import { useTaskMetrics } from "../../hooks/useTasks";

export function TaskMetricsStrip() {
  const { data } = useTaskMetrics();
  const items = [
    { label: "Total", value: data?.total, cls: "text-slate-900" },
    { label: "Open", value: data?.open, cls: "text-accent" },
    { label: "Completed", value: data?.completed, cls: "text-emerald-600" },
    { label: "Overdue", value: data?.overdue, cls: data?.overdue ? "text-red-600" : "text-slate-900" },
  ];
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Task summary">
      {items.map((i) => (
        <div key={i.label} className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5">
          <dt className="text-xs font-medium text-slate-500">{i.label}</dt>
          <dd className={`mt-0.5 text-2xl font-semibold tabular-nums ${i.cls}`}>{i.value ?? "–"}</dd>
        </div>
      ))}
    </dl>
  );
}
