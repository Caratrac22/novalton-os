import "server-only";
import { fetchScopedJson, isRecord, isTimestamp, isUuid } from "@/lib/api/scoped";

export const TASK_STATUSES = ["BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "REVIEW", "DONE", "CANCELLED"] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];
export type Task = Readonly<{ id: string; projectId: string; title: string; description: string | null; status: TaskStatus; createdAt: string; updatedAt: string }>;

function parseTask(value: unknown): Task | null {
  if (!isRecord(value) || !isUuid(value.id) || !isUuid(value.project_id) || typeof value.title !== "string" || !(value.description === null || typeof value.description === "string") || !TASK_STATUSES.includes(value.status as TaskStatus) || !isTimestamp(value.created_at) || !isTimestamp(value.updated_at)) return null;
  return { id: value.id, projectId: value.project_id, title: value.title, description: value.description, status: value.status as TaskStatus, createdAt: value.created_at, updatedAt: value.updated_at };
}

export async function getProjectTasks(projectId: string, offset = 0, limit = 100): Promise<Task[]> {
  if (!isUuid(projectId)) throw new Error("Invalid project selection");
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new Error("Invalid page");
  const value = await fetchScopedJson(`projects/${projectId}/tasks?limit=${limit}&offset=${offset}`);
  if (!isRecord(value) || !Array.isArray(value.items) || value.limit !== limit || value.offset !== offset || value.items.length > limit) throw new Error("Invalid task response");
  const tasks = value.items.map(parseTask);
  if (tasks.some((task) => task === null)) throw new Error("Invalid task response");
  return tasks as Task[];
}

export async function getProjectTask(projectId: string, taskId: string): Promise<Task> {
  if (!isUuid(projectId) || !isUuid(taskId)) throw new Error("Invalid task selection");
  const task = parseTask(await fetchScopedJson(`projects/${projectId}/tasks/${taskId}`));
  if (!task || task.projectId !== projectId) throw new Error("Invalid task response");
  return task;
}
