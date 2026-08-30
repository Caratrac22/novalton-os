export const WORKFLOW_RUN_STATUSES = ["CREATED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"] as const;
export type WorkflowRunStatus = (typeof WORKFLOW_RUN_STATUSES)[number];
export const WORKFLOW_STEP_STATUSES = ["PENDING", "READY", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"] as const;
export type WorkflowStepStatus = (typeof WORKFLOW_STEP_STATUSES)[number];

export type WorkflowStep = Readonly<{
  id: string;
  step_key: string;
  title: string;
  step_type: "AGENT_TASK" | "MANUAL_REVIEW" | "SYSTEM";
  assigned_capability: string | null;
  agent_definition_id: string | null;
  position: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  depends_on: string[];
}>;

export type WorkflowStepRun = Readonly<{
  id: string;
  workflow_step_id: string;
  status: WorkflowStepStatus;
  agent_run_id: string | null;
  failure_code: string | null;
  started_at: string | null;
  completed_at: string | null;
}>;

export type ChallengeLevel = "HUMAN_REVIEW_RECOMMENDED" | "BLOCK_RECOMMENDED";
export type QAVerdict = "PASS" | "PASS_WITH_WARNINGS" | "FAIL" | "INCONCLUSIVE";
export type ChallengeDecision = "ACCEPT_RESULT" | "REJECT_RESULT";
export type OperatorChallenge = Readonly<{
  challenge_level: ChallengeLevel;
  result_status: "COMPLETED" | "PARTIAL";
  specialization_role: "developer_manager" | "developer_worker" | "qa_worker" | null;
  qa_verdict: QAVerdict | null;
  decision: ChallengeDecision | null;
  decided_at: string | null;
}>;
export type OperatorModelRun = Readonly<{
  id: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  provider_id: string;
  provider_model_id: string;
  execution_target_class: "LOCAL" | "REMOTE" | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  failure_code: string | null;
  recovery_attempt_kind: "INITIAL" | "TRUNCATION" | "CONTRACT_REPAIR";
  recovery_attempt_index: number;
}>;
export type OperatorAgentRun = Readonly<{
  id: string;
  status: "CREATED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  agent_name: string;
  agent_slug: string;
  failure_code: string | null;
  model_runs: OperatorModelRun[];
}>;
export type OperatorStepDetail = Readonly<{
  workflow_step_run_id: string;
  specialization_role: "developer_manager" | "developer_worker" | "qa_worker" | null;
  challenge: OperatorChallenge | null;
  agent_run: OperatorAgentRun | null;
}>;

export type WorkflowPlan = Readonly<{ id: string; version: number; title: string; summary: string | null; steps: WorkflowStep[] }>;
export type WorkflowRun = Readonly<{
  id: string;
  task_id: string;
  workflow_plan_id: string;
  plan_version: number;
  status: WorkflowRunStatus;
  failure_code: string | null;
  step_runs: WorkflowStepRun[];
}>;
export type DevelopmentWorkflow = Readonly<{ workflow_plan: WorkflowPlan; workflow_run: WorkflowRun }>;
export type OperatorWorkflow = Readonly<{
  workflow_plan: WorkflowPlan;
  workflow_run: WorkflowRun;
  step_details: OperatorStepDetail[];
  qa_verdict: QAVerdict | null;
}>;
export type AdvanceResult = Readonly<{
  workflow_run_id: string;
  workflow_status: WorkflowRunStatus;
  workflow_step_run_id: string | null;
  step_key: string | null;
  step_status: WorkflowStepStatus | null;
  outcome: "STEP_COMPLETED" | "WORKFLOW_COMPLETED" | "STEP_FAILED" | "WORKFLOW_FAILED" | "WAITING_FOR_HUMAN" | "NO_RUNNABLE_STEP" | "CANCELLED";
  reason_code: string | null;
  challenge_level: "NONE" | "HUMAN_REVIEW_RECOMMENDED" | "BLOCK_RECOMMENDED" | null;
  remaining_ready: number;
  remaining_pending: number;
}>;
