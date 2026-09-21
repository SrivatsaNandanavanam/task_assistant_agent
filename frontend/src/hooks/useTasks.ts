import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TaskFilters } from "../types";

export function useTasks(filters: TaskFilters) {
  return useQuery({ queryKey: ["tasks", filters], queryFn: () => api.listTasks(filters), placeholderData: (p) => p });
}

export function useTaskMetrics() {
  return useQuery({ queryKey: ["taskMetrics"], queryFn: api.metrics });
}

/** Refresh the task list and the metrics strip after anything changes task state. */
export function useRefreshTasks() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ["tasks"] }), qc.invalidateQueries({ queryKey: ["taskMetrics"] })]);
}

export function useTaskActions() {
  const refresh = useRefreshTasks();
  const opts = { onSuccess: refresh };
  return {
    create: useMutation({ mutationFn: api.createTask, ...opts }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.updateTask(id, body),
      ...opts,
    }),
    complete: useMutation({ mutationFn: api.completeTask, ...opts }),
    reopen: useMutation({ mutationFn: api.reopenTask, ...opts }),
    remove: useMutation({ mutationFn: api.deleteTask, ...opts }),
    seed: useMutation({ mutationFn: api.seed, ...opts }),
  };
}
