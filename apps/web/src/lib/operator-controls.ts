import type { ChallengeDecision, ChallengeLevel, WorkflowRun, WorkflowStep } from "./api/workflow-types";

export function orderedWorkflowSteps(steps: readonly WorkflowStep[]): WorkflowStep[] {
  return [...steps].sort((left, right) => left.position - right.position);
}

export function canAdvanceWorkflow(run: WorkflowRun, busy = false): boolean {
  return !busy && (run.status === "CREATED" || run.status === "RUNNING") && run.step_runs.some((step) => step.status === "READY");
}

export function challengeDecisions(level: ChallengeLevel): ChallengeDecision[] {
  return level === "BLOCK_RECOMMENDED" ? ["REJECT_RESULT"] : ["ACCEPT_RESULT", "REJECT_RESULT"];
}

export function challengeResolutionBody(decision: ChallengeDecision, reason: string): Readonly<{ decision: ChallengeDecision; reason: string | null }> {
  return { decision, reason: reason.trim() || null };
}
