import type { WorkflowRunStatus } from "./api/workflow-types";

export type WorkflowSnapshot = Readonly<{ status: WorkflowRunStatus }>;
export type WorkflowSummary = Readonly<Record<WorkflowRunStatus, number>>;

export function summarizeWorkflows(runs: readonly WorkflowSnapshot[]): WorkflowSummary {
  const summary: Record<WorkflowRunStatus, number> = {
    CREATED: 0, RUNNING: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0,
  };
  for (const run of runs) summary[run.status] += 1;
  return summary;
}
