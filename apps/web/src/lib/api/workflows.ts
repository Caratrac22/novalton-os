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
function boundedStrings(value: unknown, maxItems: number, maxLength: number): value is string[] { return Array.isArray(value) && value.length <= maxItems && value.every((item) => typeof item === "string" && item.length > 0 && item.length <= maxLength); }
function onlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean { const allowed = new Set(keys); return Object.keys(value).every((key) => allowed.has(key)) && keys.every((key) => key in value); }
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
  if (!isRecord(value) || !["HUMAN_REVIEW_RECOMMENDED", "BLOCK_RECOMMENDED"].includes(String(value.challenge_level)) || !["COMPLETED", "PARTIAL"].includes(String(value.result_status)) || !nullableString(value.specialization_role) || !nullableString(value.qa_verdict) || !nullableString(value.decision) || !(value.decided_at === null || isTimestamp(value.decided_at))) return false;
  if (!["AVAILABLE", "MISSING", "NOT_APPLICABLE"].includes(String(value.review_summary_status))) return false;
  const summary = value.safe_review_summary;
  if (value.review_summary_status === "AVAILABLE") return isQAReviewSummary(summary);
  if (summary !== null) return false;
  return value.review_summary_status === "MISSING" ? value.specialization_role === "qa_worker" : value.specialization_role !== "qa_worker";
}
function isQAReviewSummary(value: unknown): boolean {
  if (!isRecord(value) || !onlyKeys(value, ["schema_version", "verdict", "challenge_level", "challenge_reason", "challenge_evidence_references", "suggested_action", "validation_summary", "warnings", "recommendations", "acceptance_results", "concerns"])) return false;
  if (value.schema_version !== 1 || !["PASS", "PASS_WITH_WARNINGS", "FAIL", "INCONCLUSIVE"].includes(String(value.verdict)) || !["HUMAN_REVIEW_RECOMMENDED", "BLOCK_RECOMMENDED"].includes(String(value.challenge_level))) return false;
  if (typeof value.challenge_reason !== "string" || value.challenge_reason.length < 1 || value.challenge_reason.length > 2000 || !boundedStrings(value.challenge_evidence_references, 16, 128) || !(value.suggested_action === null || (typeof value.suggested_action === "string" && value.suggested_action.length > 0 && value.suggested_action.length <= 500)) || typeof value.validation_summary !== "string" || value.validation_summary.length < 1 || value.validation_summary.length > 3000) return false;
  if (!Array.isArray(value.warnings) || value.warnings.length > 40 || !value.warnings.every((item) => isReviewMessage(item, ["REGRESSION_RISK", "BLOCKER"]))) return false;
  if (!Array.isArray(value.recommendations) || value.recommendations.length > 72 || !value.recommendations.every((item) => isReviewMessage(item, ["TEST", "SECURITY_REVIEW", "MANUAL_REVIEW"]))) return false;
  if (!Array.isArray(value.acceptance_results) || value.acceptance_results.length < 1 || value.acceptance_results.length > 24 || !value.acceptance_results.every(isAcceptanceResult)) return false;
  return Array.isArray(value.concerns) && value.concerns.length <= 32 && value.concerns.every(isReviewConcern);
}
function isReviewMessage(value: unknown, categories: readonly string[]): boolean { return isRecord(value) && onlyKeys(value, ["category", "message"]) && categories.includes(String(value.category)) && typeof value.message === "string" && value.message.length > 0 && value.message.length <= 500; }
function isAcceptanceResult(value: unknown): boolean { return isRecord(value) && onlyKeys(value, ["criterion_id", "status", "rationale", "evidence_references"]) && typeof value.criterion_id === "string" && value.criterion_id.length > 0 && value.criterion_id.length <= 100 && ["PASS", "FAIL", "NOT_VERIFIED"].includes(String(value.status)) && typeof value.rationale === "string" && value.rationale.length > 0 && value.rationale.length <= 1000 && boundedStrings(value.evidence_references, 16, 128); }
function isReviewConcern(value: unknown): boolean { return isRecord(value) && onlyKeys(value, ["defect_key", "title", "severity", "component_path", "description", "affected_criteria", "remediation_summary"]) && typeof value.defect_key === "string" && value.defect_key.length > 0 && value.defect_key.length <= 100 && typeof value.title === "string" && value.title.length > 0 && value.title.length <= 300 && ["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(String(value.severity)) && (value.component_path === null || (typeof value.component_path === "string" && value.component_path.length > 0 && value.component_path.length <= 300)) && typeof value.description === "string" && value.description.length > 0 && value.description.length <= 2000 && boundedStrings(value.affected_criteria, 12, 100) && typeof value.remediation_summary === "string" && value.remediation_summary.length > 0 && value.remediation_summary.length <= 1000; }
function isAgentRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && typeof value.status === "string" && typeof value.agent_name === "string" && typeof value.agent_slug === "string" && nullableString(value.failure_code) && Array.isArray(value.model_runs) && value.model_runs.every(isModelRun) && Array.isArray(value.tool_calls) && value.tool_calls.every(isToolCall);
}
function isModelRun(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && typeof value.status === "string" && typeof value.provider_id === "string" && typeof value.provider_model_id === "string" && nullableString(value.execution_target_class) && nullableNumber(value.input_tokens) && nullableNumber(value.output_tokens) && nullableNumber(value.total_tokens) && nullableNumber(value.duration_ms) && nullableString(value.failure_code) && typeof value.recovery_attempt_kind === "string" && typeof value.recovery_attempt_index === "number";
}
function isToolCall(value: unknown): boolean {
  return isRecord(value) && isUuid(value.id) && typeof value.tool_name === "string" && typeof value.status === "string" && nullableString(value.policy_effect) && (value.approval_request_id === null || isUuid(value.approval_request_id)) && value.execution_target_class === "LOCAL" && nullableNumber(value.duration_ms) && nullableNumber(value.result_count) && nullableNumber(value.bytes_returned) && (value.truncated === null || typeof value.truncated === "boolean") && nullableString(value.failure_code) && nullableString(value.target_path) && nullableString(value.mutation_fingerprint) && nullableNumber(value.before_lines) && nullableNumber(value.after_lines) && nullableString(value.diff_preview) && (value.diff_truncated === null || typeof value.diff_truncated === "boolean");
}

export async function postWorkflow(path: string, body?: unknown): Promise<Response> {
  return fetch(`${getApiBaseUrl()}${scopedApiPath(path)}`, { method: "POST", cache: "no-store", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000) });
}
