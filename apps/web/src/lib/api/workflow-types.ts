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
