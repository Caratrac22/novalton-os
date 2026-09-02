import assert from "node:assert/strict";
import test from "node:test";
import { canAdvanceWorkflow, canResolveChallenge, challengeDecisions, challengeResolutionBody, orderedWorkflowSteps } from "./operator-controls.ts";
import type { OperatorChallenge, WorkflowRun, WorkflowStep } from "./api/workflow-types.ts";

const ids = ["10000000-0000-4000-8000-000000000001", "10000000-0000-4000-8000-000000000002", "10000000-0000-4000-8000-000000000003"];
const steps = [
  { id: ids[2], step_key: "qa_validate", title: "QA", step_type: "AGENT_TASK", assigned_capability: null, agent_definition_id: null, position: 2, risk_level: null, depends_on: ["developer_execute"] },
  { id: ids[0], step_key: "manager_plan", title: "Manager", step_type: "AGENT_TASK", assigned_capability: null, agent_definition_id: null, position: 0, risk_level: null, depends_on: [] },
  { id: ids[1], step_key: "developer_execute", title: "Developer", step_type: "AGENT_TASK", assigned_capability: null, agent_definition_id: null, position: 1, risk_level: null, depends_on: ["manager_plan"] },
] satisfies WorkflowStep[];

function run(status: WorkflowRun["status"], stepStatus: WorkflowRun["step_runs"][number]["status"]): WorkflowRun {
  return { id: ids[0], task_id: ids[1], workflow_plan_id: ids[2], plan_version: 1, status, failure_code: null, step_runs: [{ id: ids[0], workflow_step_id: ids[0], status: stepStatus, agent_run_id: null, failure_code: null, started_at: null, completed_at: null }] };
}

test("renders the canonical three-step order from persisted positions", () => {
  assert.deepEqual(orderedWorkflowSteps(steps).map((step) => step.step_key), ["manager_plan", "developer_execute", "qa_validate"]);
  assert.deepEqual(steps.map((step) => step.step_key), ["qa_validate", "manager_plan", "developer_execute"]);
});

test("advance is available only for one READY server step and is disabled while busy or terminal", () => {
  assert.equal(canAdvanceWorkflow(run("CREATED", "READY")), true);
  assert.equal(canAdvanceWorkflow(run("RUNNING", "READY"), true), false);
  assert.equal(canAdvanceWorkflow(run("RUNNING", "RUNNING")), false);
  assert.equal(canAdvanceWorkflow(run("COMPLETED", "READY")), false);
  assert.equal(canAdvanceWorkflow(run("FAILED", "READY")), false);
});

test("BLOCK_RECOMMENDED never offers acceptance", () => {
  assert.deepEqual(challengeDecisions("HUMAN_REVIEW_RECOMMENDED"), ["ACCEPT_RESULT", "REJECT_RESULT"]);
  assert.deepEqual(challengeDecisions("BLOCK_RECOMMENDED"), ["REJECT_RESULT"]);
});

test("historical QA challenges without a safe summary fail closed for UI decisions", () => {
  const historical = { challenge_level: "HUMAN_REVIEW_RECOMMENDED", result_status: "COMPLETED", specialization_role: "qa_worker", qa_verdict: "PASS_WITH_WARNINGS", review_summary_status: "MISSING", safe_review_summary: null, decision: null, decided_at: null } satisfies OperatorChallenge;
  const manager = { ...historical, specialization_role: "developer_manager", qa_verdict: null, review_summary_status: "NOT_APPLICABLE" } satisfies OperatorChallenge;
  assert.equal(canResolveChallenge(historical), false);
  assert.equal(canResolveChallenge(manager), true);
});

test("challenge requests contain only decision and bounded optional reason fields", () => {
  const body = challengeResolutionBody("ACCEPT_RESULT", "  reviewed locally  ");
  assert.deepEqual(body, { decision: "ACCEPT_RESULT", reason: "reviewed locally" });
  assert.deepEqual(Object.keys(body).sort(), ["decision", "reason"]);
  for (const forbidden of ["actor", "status", "verdict", "provider", "policy", "permission", "tool"]) assert.equal(forbidden in body, false);
  assert.deepEqual(challengeResolutionBody("REJECT_RESULT", "   "), { decision: "REJECT_RESULT", reason: null });
});
