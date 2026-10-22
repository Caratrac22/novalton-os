import "server-only";
import { fetchScopedJson, isRecord, isTimestamp, isUuid } from "@/lib/api/scoped";

export const PROJECT_STATUSES = ["ACTIVE", "PAUSED", "ARCHIVED"] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];
export type Project = Readonly<{ id: string; workspaceId: string; name: string; slug: string; description: string | null; status: ProjectStatus; createdAt: string; updatedAt: string }>;

function parseProject(value: unknown): Project | null {
  if (!isRecord(value) || !isUuid(value.id) || !isUuid(value.workspace_id) || typeof value.name !== "string" || typeof value.slug !== "string" || !(value.description === null || typeof value.description === "string") || !PROJECT_STATUSES.includes(value.status as ProjectStatus) || !isTimestamp(value.created_at) || !isTimestamp(value.updated_at)) return null;
  return { id: value.id, workspaceId: value.workspace_id, name: value.name, slug: value.slug, description: value.description, status: value.status as ProjectStatus, createdAt: value.created_at, updatedAt: value.updated_at };
}

export async function getProjects(offset = 0, limit = 100): Promise<Project[]> {
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new Error("Invalid page");
  const value = await fetchScopedJson(`projects?limit=${limit}&offset=${offset}`);
  if (!isRecord(value) || !Array.isArray(value.items) || value.limit !== limit || value.offset !== offset || value.items.length > limit) throw new Error("Invalid project response");
  const projects = value.items.map(parseProject);
  if (projects.some((project) => project === null)) throw new Error("Invalid project response");
  return projects as Project[];
}

export async function getProject(projectId: string): Promise<Project> {
  if (!isUuid(projectId)) throw new Error("Invalid project");
  const project = parseProject(await fetchScopedJson(`projects/${projectId}`));
  if (!project) throw new Error("Invalid project response");
  return project;
}
