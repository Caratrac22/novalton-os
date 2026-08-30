import "server-only";
import { fetchScopedJson, isRecord, isTimestamp, isUuid } from "@/lib/api/scoped";
import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";
import type { OperatorWorkflow, WorkflowPlan, WorkflowRun, WorkflowStep } from "@/lib/api/workflow-types";

export async function getWorkflowRuns(): Promise<WorkflowRun[]> {
  const value = await fetchScopedJson("workflow-runs?limit=100&offset=0");
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("Invalid workflow response");
  return value.items.filter(isWorkflowRun) as WorkflowRun[];
}

export async function getWorkflowPlan(planId: string): Promise<WorkflowPlan> {
  const value = await fetchScopedJson(`workflow-plans/${planId}`);
  if (!isRecord(value) || !isUuid(value.id) || typeof value.version !== "number" || typeof value.title !== "string" || !Array.isArray(value.steps)) throw new Error("Invalid workflow plan response");
  return { id: value.id, version: value.version, title: value.title, summary: typeof value.summary === "string" ? value.summary : null, steps: value.steps as WorkflowStep[] };
}

export async function getOperatorWorkflow(runId: string): Promise<OperatorWorkflow> {
  if (!isUuid(runId)) throw new Error("Invalid workflow run");
  return parseOperatorWorkflow(await fetchScopedJson(`workflow-runs/${runId}/operator-view`));
}

function isWorkflowRun(value: unknown): value is WorkflowRun {
  return isRecord(value) && isUuid(value.id) && isUuid(value.task_id) && isUuid(value.workflow_plan_id) && typeof value.plan_version === "number" && typeof value.status === "string" && Array.isArray(value.step_runs) && value.step_runs.every(isStepRun);
}
function isStepRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && isUuid(value.workflow_step_id) && typeof value.status === "string" && (value.agent_run_id === null || isUuid(value.agent_run_id)) && (value.failure_code === null || typeof value.failure_code === "string") && (value.started_at === null || isTimestamp(value.started_at)) && (value.completed_at === null || isTimestamp(value.completed_at));
}

function nullableString(value: unknown): value is string | null { return value === null || typeof value === "string"; }
function nullableNumber(value: unknown): value is number | null { return value === null || typeof value === "number"; }
function parseOperatorWorkflow(value: unknown): OperatorWorkflow {
  if (!isRecord(value) || !isRecord(value.workflow_plan) || !isWorkflowRun(value.workflow_run) || !Array.isArray(value.step_details)) throw new Error("Invalid operator workflow response");
  const planValue = value.workflow_plan;
  if (!isUuid(planValue.id) || typeof planValue.version !== "number" || typeof planValue.title !== "string" || !Array.isArray(planValue.steps)) throw new Error("Invalid operator workflow response");
  const steps = planValue.steps;
  if (!steps.every((step) => isRecord(step) && isUuid(step.id) && typeof step.step_key === "string" && typeof step.title === "string" && typeof step.position === "number")) throw new Error("Invalid operator workflow response");
  const details = value.step_details;
  for (const detail of details) {
    if (!isRecord(detail) || !isUuid(detail.workflow_step_run_id) || !(detail.specialization_role === null || typeof detail.specialization_role === "string") || !(detail.challenge === null || isChallenge(detail.challenge)) || !(detail.agent_run === null || isAgentRun(detail.agent_run))) throw new Error("Invalid operator workflow response");
  }
  if (!(value.qa_verdict === null || ["PASS", "PASS_WITH_WARNINGS", "FAIL", "INCONCLUSIVE"].includes(String(value.qa_verdict)))) throw new Error("Invalid operator workflow response");
  return { workflow_plan: { id: planValue.id, version: planValue.version, title: planValue.title, summary: typeof planValue.summary === "string" ? planValue.summary : null, steps: steps as WorkflowStep[] }, workflow_run: value.workflow_run, step_details: details as OperatorWorkflow["step_details"], qa_verdict: value.qa_verdict as OperatorWorkflow["qa_verdict"] };
}
function isChallenge(value: unknown): boolean {
  return isRecord(value) && ["HUMAN_REVIEW_RECOMMENDED", "BLOCK_RECOMMENDED"].includes(String(value.challenge_level)) && ["COMPLETED", "PARTIAL"].includes(String(value.result_status)) && nullableString(value.specialization_role) && nullableString(value.qa_verdict) && nullableString(value.decision) && (value.decided_at === null || isTimestamp(value.decided_at));
}
function isAgentRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && typeof value.status === "string" && typeof value.agent_name === "string" && typeof value.agent_slug === "string" && nullableString(value.failure_code) && Array.isArray(value.model_runs) && value.model_runs.every(isModelRun);
}
function isModelRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && typeof value.status === "string" && typeof value.provider_id === "string" && typeof value.provider_model_id === "string" && nullableString(value.execution_target_class) && nullableNumber(value.input_tokens) && nullableNumber(value.output_tokens) && nullableNumber(value.total_tokens) && nullableNumber(value.duration_ms) && nullableString(value.failure_code) && typeof value.recovery_attempt_kind === "string" && typeof value.recovery_attempt_index === "number";
}

export async function postWorkflow(path: string, body?: unknown): Promise<Response> {
  return fetch(`${getApiBaseUrl()}${scopedApiPath(path)}`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
}
