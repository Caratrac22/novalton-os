import "server-only";
import { fetchScopedJson, isRecord, isTimestamp, isUuid } from "@/lib/api/scoped";
import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import type { WorkflowRun } from "@/lib/api/workflow-types";

export async function getWorkflowRuns(): Promise<WorkflowRun[]> {
  const value = await fetchScopedJson("workflow-runs?limit=100&offset=0");
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("Invalid workflow response");
  return value.items.filter(isWorkflowRun) as WorkflowRun[];
}

export async function getWorkflowPlan(planId: string): Promise<import("@/lib/api/workflow-types").WorkflowPlan> {
  const value = await fetchScopedJson(`workflow-plans/${planId}`);
  if (!isRecord(value) || !isUuid(value.id) || typeof value.version !== "number" || typeof value.title !== "string" || !Array.isArray(value.steps)) throw new Error("Invalid workflow plan response");
  return { id: value.id, version: value.version, title: value.title, summary: typeof value.summary === "string" ? value.summary : null, steps: value.steps as import("@/lib/api/workflow-types").WorkflowStep[] };
}

function isWorkflowRun(value: unknown): value is WorkflowRun {
  return isRecord(value) && isUuid(value.id) && isUuid(value.task_id) && isUuid(value.workflow_plan_id) && typeof value.plan_version === "number" && typeof value.status === "string" && Array.isArray(value.step_runs) && value.step_runs.every(isStepRun);
}
function isStepRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && isUuid(value.workflow_step_id) && typeof value.status === "string" && (value.agent_run_id === null || isUuid(value.agent_run_id)) && (value.failure_code === null || typeof value.failure_code === "string") && (value.started_at === null || isTimestamp(value.started_at)) && (value.completed_at === null || isTimestamp(value.completed_at));
}

export async function postWorkflow(path: string, body?: unknown): Promise<Response> {
  return fetch(`${getApiBaseUrl()}${scopedApiPath(path)}`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
}
