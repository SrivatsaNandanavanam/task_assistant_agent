const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

export function formatDue(iso: string): string {
  const due = new Date(iso);
  const days = Math.round((startOfDay(due) - startOfDay(new Date())) / 86_400_000);
  const time = due.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  let day: string;
  if (days === 0) day = "Today";
  else if (days === 1) day = "Tomorrow";
  else if (days === -1) day = "Yesterday";
  else if (days > 1 && days < 7) day = due.toLocaleDateString([], { weekday: "long" });
  else day = due.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${day} • ${time}`;
}

/** Value for <input type="datetime-local"> in the user's local timezone. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
