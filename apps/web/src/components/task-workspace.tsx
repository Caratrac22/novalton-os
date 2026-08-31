"use client";

import { useCallback, useRef, useState } from "react";
import { ActivityFeed } from "@/components/activity-feed";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { humanize } from "@/lib/format";
import { canAdvanceWorkflow, challengeDecisions, challengeResolutionBody, orderedWorkflowSteps } from "@/lib/operator-controls";
import type { AdvanceResult, ChallengeDecision, OperatorChallenge, OperatorStepDetail, OperatorWorkflow, WorkflowRun, WorkflowStep } from "@/lib/api/workflow-types";

type TaskWorkspaceProps = Readonly<{ projectId: string; taskId: string; taskTitle: string; initialWorkflow: OperatorWorkflow | null }>;
const stepRoles: Record<string, string> = { manager_plan: "Developer Manager", developer_execute: "Developer Worker", qa_validate: "QA Worker" };
const stepDescriptions: Record<string, string> = { manager_plan: "Shapes the bounded development assignment.", developer_execute: "Carries out the governed development assignment.", qa_validate: "Checks the result against the acceptance criteria." };
const runTones: Record<string, StatusTone> = { CREATED: "neutral", RUNNING: "positive", COMPLETED: "positive", FAILED: "negative", CANCELLED: "negative" };
const stepTones: Record<string, StatusTone> = { PENDING: "neutral", READY: "neutral", RUNNING: "positive", COMPLETED: "positive", FAILED: "negative", CANCELLED: "negative" };

export function TaskWorkspace({ projectId, taskId, taskTitle, initialWorkflow }: TaskWorkspaceProps) {
  const [workflow, setWorkflow] = useState<OperatorWorkflow | null>(initialWorkflow);
  const [objective, setObjective] = useState("");
  const [criteria, setCriteria] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<AdvanceResult | null>(null);
  const refreshing = useRef(false);
  const operationInFlight = useRef(false);

  const refreshWorkflow = useCallback(async (runId: string) => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const response = await fetch(`/api/workflows/${runId}/operator-view`, { cache: "no-store" });
      const value = await response.json() as OperatorWorkflow & { message?: string };
      if (!response.ok) throw new Error(value.message || "The current workflow state is unavailable.");
      setWorkflow(value);
    } finally { refreshing.current = false; }
  }, []);
  const activeRunId = workflow?.workflow_run.id;
  const handleWorkflowEvent = useCallback(() => { if (activeRunId) void refreshWorkflow(activeRunId); }, [activeRunId, refreshWorkflow]);

  async function createWorkflow(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    const acceptanceCriteria = criteria.split("\n").map((item) => item.trim()).filter(Boolean);
    try {
      const response = await fetch("/api/workflows/development", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, taskId, objective: objective.trim(), acceptanceCriteria }) });
      const value = await response.json() as { workflow_run?: { id?: string }; message?: string };
      if (!response.ok || !value.workflow_run?.id) throw new Error(value.message || "The development workflow could not be created.");
      await refreshWorkflow(value.workflow_run.id);
      setObjective(""); setCriteria("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The development workflow could not be created."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  async function advance() {
    if (!workflow || operationInFlight.current || !canAdvance(workflow.workflow_run)) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflow.workflow_run.id}/advance`, { method: "POST" });
      const result = await response.json() as AdvanceResult & { message?: string };
      if (!response.ok) throw new Error(result.message || "The workflow could not be advanced.");
      setLastResult(result);
      await refreshWorkflow(workflow.workflow_run.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The workflow could not be advanced."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  async function resolveChallenge(stepRunId: string, decision: ChallengeDecision, reason: string | null) {
    if (!workflow || operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflow.workflow_run.id}/steps/${stepRunId}/challenge-resolution`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(challengeResolutionBody(decision, reason || "")) });
      const value = await response.json() as { message?: string };
      if (!response.ok) throw new Error(value.message || "The challenge could not be resolved.");
      setLastResult(null);
      await refreshWorkflow(workflow.workflow_run.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The challenge could not be resolved."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  if (!workflow) return <section className="workflow-card" aria-labelledby="workflow-create-title"><div className="workflow-card-header"><div><p className="eyebrow">Governed execution</p><h2 id="workflow-create-title">Create development workflow</h2><p>Start the fixed Manager → Developer Worker → QA sequence. Each Run next step action processes at most one server-authorized step.</p></div></div><form className="workflow-form" onSubmit={createWorkflow}><label>Objective<textarea required maxLength={1500} value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={`What should be delivered for “${taskTitle}”?`} /></label><label>Acceptance criteria <span>(one per line, up to 24)</span><textarea required value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder="The result meets the task requirements\nThe change is ready for QA" /></label>{error ? <InlineError>{error}</InlineError> : null}<button className="primary-button" disabled={busy}>{busy ? "Creating workflow…" : "Create workflow"}</button></form></section>;

  const { workflow_plan: plan, workflow_run: run } = workflow;
  const orderedSteps = orderedWorkflowSteps(plan.steps);
  const current = orderedSteps.find((step) => run.step_runs.find((item) => item.workflow_step_id === step.id)?.status === "READY");
  const pendingChallenge = workflow.step_details.find((detail) => detail.challenge?.decision === null)?.challenge;
  const controlTitle = run.status === "COMPLETED" ? "Workflow complete" : run.status === "FAILED" ? "Workflow failed" : pendingChallenge ? "Human review required" : current ? `Next step: ${stepRoles[current.step_key] || humanize(current.step_key)}` : "No runnable step";
  return <div className="operator-stack"><section className="workflow-card" aria-labelledby="workflow-title"><div className="workflow-card-header"><div><p className="eyebrow">Development workflow · v{plan.version}</p><h2 id="workflow-title">{plan.title}</h2><p>{plan.summary}</p></div><div className="workflow-status-stack"><StatusBadge tone={runTones[run.status]}>{humanize(run.status)}</StatusBadge>{pendingChallenge ? <StatusBadge tone="neutral">Waiting for human</StatusBadge> : null}</div></div><div className="workflow-control"><div><strong>{controlTitle}</strong><span>One click sends exactly one bodyless Orchestrator advance request.</span></div><button className="primary-button" onClick={advance} disabled={busy || !canAdvance(run)}>{busy ? "Request in progress…" : canAdvance(run) ? "Run next step" : "No advance available"}</button></div>{workflow.qa_verdict ? <div className={`qa-verdict qa-verdict-${workflow.qa_verdict.toLowerCase()}`}><span>Final QA verdict</span><strong>{humanize(workflow.qa_verdict)}</strong></div> : null}{error ? <InlineError>{error}</InlineError> : null}{lastResult ? <ResultBanner result={lastResult} /> : null}<ol className="workflow-steps">{orderedSteps.map((step) => { const stepRun = run.step_runs.find((item) => item.workflow_step_id === step.id); const detail = workflow.step_details.find((item) => item.workflow_step_run_id === stepRun?.id); return <WorkflowStepCard key={step.id} step={step} stepRun={stepRun} detail={detail} busy={busy} onResolve={resolveChallenge} />; })}</ol></section><ActivityFeed projectId={projectId} taskId={taskId} workflowRunId={run.id} onWorkflowEvent={handleWorkflowEvent} /></div>;
}

function canAdvance(run: WorkflowRun) { return canAdvanceWorkflow(run); }
function InlineError({ children }: Readonly<{ children: React.ReactNode }>) { return <p className="inline-error" role="alert">{children}</p>; }
function ResultBanner({ result }: Readonly<{ result: AdvanceResult }>) { const waiting = result.outcome === "WAITING_FOR_HUMAN"; return <div className={`workflow-result ${waiting ? "is-waiting" : result.outcome.includes("FAILED") ? "is-failed" : ""}`} role="status"><strong>{waiting ? "Human intervention required" : humanize(result.outcome)}</strong><span>{reasonText(result.reason_code, result.challenge_level)}</span></div>; }

function WorkflowStepCard({ step, stepRun, detail, busy, onResolve }: Readonly<{ step: WorkflowStep; stepRun?: WorkflowRun["step_runs"][number]; detail?: OperatorStepDetail; busy: boolean; onResolve: (stepRunId: string, decision: ChallengeDecision, reason: string | null) => Promise<void> }>) {
  const status = stepRun?.status || "PENDING";
  return <li className={`workflow-step workflow-step-${status.toLowerCase()}`}><div className="workflow-step-index">{step.position + 1}</div><div className="workflow-step-content"><div className="workflow-step-heading"><div><span className="workflow-role">{stepRoles[step.step_key] || humanize(step.step_key)}</span><h3>{step.title}</h3></div><StatusBadge tone={stepTones[status]}>{humanize(status)}</StatusBadge></div><p>{stepDescriptions[step.step_key] || "Governed workflow step."}</p>{stepRun?.failure_code ? <p className="workflow-reason">{reasonText(stepRun.failure_code, null)}</p> : null}{detail?.agent_run ? <AgentMetadata detail={detail} /> : null}{detail?.challenge?.decision === null && stepRun ? <ChallengePanel challenge={detail.challenge} stepRunId={stepRun.id} busy={busy} onResolve={onResolve} /> : detail?.challenge?.decision ? <p className="challenge-resolved">Agent challenge resolved: {humanize(detail.challenge.decision)}</p> : null}</div></li>;
}

function AgentMetadata({ detail }: Readonly<{ detail: OperatorStepDetail }>) {
  const agent = detail.agent_run;
  if (!agent) return null;
  return <div className="execution-metadata"><div className="execution-heading"><span>Execution metadata</span><strong>{humanize(agent.status)}</strong></div>{agent.model_runs.length === 0 ? <p>No provider invocation was recorded for this AgentRun.</p> : agent.model_runs.map((model) => <dl className="model-metadata" key={model.id}><div><dt>Provider / model</dt><dd>{model.provider_id} / {model.provider_model_id}</dd></div><div><dt>Target</dt><dd>{model.execution_target_class ? humanize(model.execution_target_class) : "Unavailable"}</dd></div><div><dt>ModelRun</dt><dd>{humanize(model.status)}</dd></div><div><dt>Tokens</dt><dd>{model.total_tokens ?? "—"} total{model.input_tokens !== null && model.output_tokens !== null ? ` (${model.input_tokens} in / ${model.output_tokens} out)` : ""}</dd></div><div><dt>Duration</dt><dd>{model.duration_ms === null ? "—" : `${model.duration_ms} ms`}</dd></div><div><dt>Attempt</dt><dd>{humanize(model.recovery_attempt_kind)} · {model.recovery_attempt_index}</dd></div>{model.failure_code ? <div><dt>Reason</dt><dd>{humanize(model.failure_code)}</dd></div> : null}</dl>)}{agent.tool_calls.map((tool) => <dl className="model-metadata" key={tool.id}><div><dt>Trusted tool</dt><dd>{tool.tool_name}</dd></div><div><dt>Status</dt><dd>{humanize(tool.status)}</dd></div><div><dt>Policy</dt><dd>{tool.policy_effect ? humanize(tool.policy_effect) : "Not evaluated"}</dd></div><div><dt>Target</dt><dd>{humanize(tool.execution_target_class)} · Read only</dd></div><div><dt>Duration</dt><dd>{tool.duration_ms === null ? "—" : `${tool.duration_ms} ms`}</dd></div>{tool.approval_request_id ? <div><dt>ApprovalRequest</dt><dd title={tool.approval_request_id}>{tool.approval_request_id.slice(0, 8)} · exact one-action scope</dd></div> : null}{tool.result_count !== null ? <div><dt>Results</dt><dd>{tool.result_count}{tool.truncated ? " (truncated)" : ""}</dd></div> : null}{tool.bytes_returned !== null ? <div><dt>Bytes</dt><dd>{tool.bytes_returned}{tool.truncated ? " (truncated)" : ""}</dd></div> : null}{tool.failure_code ? <div><dt>Reason</dt><dd>{humanize(tool.failure_code)}</dd></div> : null}</dl>)}</div>;
}

function ChallengePanel({ challenge, stepRunId, busy, onResolve }: Readonly<{ challenge: OperatorChallenge; stepRunId: string; busy: boolean; onResolve: (stepRunId: string, decision: ChallengeDecision, reason: string | null) => Promise<void> }>) {
  const [reason, setReason] = useState("");
  const decisions = challengeDecisions(challenge.challenge_level);
  return <div className="challenge-panel" role="alert"><div><p className="eyebrow">Agent result review</p><h4>Human decision required</h4><p>This is an Agent challenge, not a Policy ApprovalRequest. Workflow state remains server-authoritative.</p></div><dl><div><dt>Challenge</dt><dd>{humanize(challenge.challenge_level)}</dd></div>{challenge.qa_verdict ? <div><dt>QA verdict</dt><dd>{humanize(challenge.qa_verdict)}</dd></div> : null}</dl><label>Decision reason <span>(optional, max 500 characters)</span><textarea maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label><div className="challenge-actions">{decisions.map((decision) => <button key={decision} className={decision === "REJECT_RESULT" ? "danger-button" : "primary-button"} disabled={busy} onClick={() => void onResolve(stepRunId, decision, reason.trim() || null)}>{busy ? "Decision in progress…" : humanize(decision)}</button>)}</div>{challenge.challenge_level === "BLOCK_RECOMMENDED" ? <p className="challenge-note">BLOCK_RECOMMENDED cannot be accepted in V1.</p> : null}</div>;
}

function reasonText(reason: string | null, challenge: AdvanceResult["challenge_level"]) { const reasons: Record<string, string> = { agent_challenge: "The active Agent result requires an explicit human decision.", step_requires_intervention: "The current step needs human review before execution can continue.", manual_review_required: "This step is waiting for a human review.", no_ready_step: "No step is currently runnable.", workflow_cancelled: "The workflow was cancelled by the governing system.", workflow_failed: "The governing workflow marked this run as failed.", agent_assignment_required: "An approved agent assignment is required before this step can run.", qa_failed: "QA returned FAIL; the workflow cannot complete successfully.", qa_inconclusive: "QA returned INCONCLUSIVE; the workflow cannot complete successfully.", agent_challenge_rejected: "The operator rejected the challenged Agent result." }; return reason ? reasons[reason] || (reason.includes("failed") ? "The workflow reported a failure for this step." : `Server reason: ${humanize(reason)}`) : challenge && challenge !== "NONE" ? `Challenge signal: ${humanize(challenge)}.` : "The server accepted the operation and returned the current state."; }
