import type { ReceiptStep } from "../../types";

const ICON: Record<ReceiptStep["status"], { glyph: string; cls: string }> = {
  done: { glyph: "✓", cls: "text-emerald-600" },
  failed: { glyph: "✕", cls: "text-red-600" },
  waiting: { glyph: "!", cls: "text-amber-600" },
  pending: { glyph: "○", cls: "text-slate-300" },
  skipped: { glyph: "–", cls: "text-slate-300" },
};

/** Collapsed-by-default disclosure showing only safe workflow metadata. */
export function AgentActivity({ steps, failed }: { steps: ReceiptStep[]; failed?: boolean }) {
  const visible = steps.filter((s) => s.key !== "approval" || s.status !== "skipped");
  return (
    <details className="group mt-2 text-xs text-slate-500">
      <summary className="inline-flex cursor-pointer select-none items-center gap-1 rounded px-1 py-0.5 hover:bg-slate-100 hover:text-slate-700">
        <span className={failed ? "text-red-600" : "text-emerald-600"}>{failed ? "✕" : "✓"}</span>
        Activity
        <span className="transition-transform group-open:rotate-180" aria-hidden>
          ▾
        </span>
      </summary>
      <ol className="mt-1.5 space-y-1 border-l border-slate-200 pl-3">
        {visible.map((s) => (
          <li key={s.key} className="flex gap-2">
            <span className={`w-3 shrink-0 text-center ${ICON[s.status].cls}`} aria-hidden>
              {ICON[s.status].glyph}
            </span>
            <span>
              <span className="text-slate-700">{s.label}</span>
              {s.detail && <span className="text-slate-400"> · {s.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}
