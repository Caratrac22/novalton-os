import "server-only";
import { fetchScopedJson, isRecord, isTimestamp, isUuid } from "@/lib/api/scoped";

export const TASK_STATUSES = ["BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "REVIEW", "DONE", "CANCELLED"] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];
export type Task = Readonly<{ id: string; projectId: string; title: string; description: string | null; status: TaskStatus; createdAt: string; updatedAt: string }>;

function parseTask(value: unknown): Task | null {
  if (!isRecord(value) || !isUuid(value.id) || !isUuid(value.project_id) || typeof value.title !== "string" || !(value.description === null || typeof value.description === "string") || !TASK_STATUSES.includes(value.status as TaskStatus) || !isTimestamp(value.created_at) || !isTimestamp(value.updated_at)) return null;
  return { id: value.id, projectId: value.project_id, title: value.title, description: value.description, status: value.status as TaskStatus, createdAt: value.created_at, updatedAt: value.updated_at };
}

export async function getProjectTasks(projectId: string): Promise<Task[]> {
  if (!isUuid(projectId)) throw new Error("Invalid project selection");
  const value = await fetchScopedJson(`projects/${projectId}/tasks?limit=100&offset=0`);
  if (!isRecord(value) || !Array.isArray(value.items) || value.limit !== 100 || value.offset !== 0) throw new Error("Invalid task response");
  const tasks = value.items.map(parseTask);
  if (tasks.some((task) => task === null)) throw new Error("Invalid task response");
  return tasks as Task[];
}
