"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityFeed } from "@/components/activity-feed";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { humanize } from "@/lib/format";
import { canAdvanceWorkflow, canResolveChallenge, challengeDecisions, challengeResolutionBody, orderedWorkflowSteps } from "@/lib/operator-controls";
import { mutationApprovalState, mutationPreviewLabel } from "@/lib/mutation-approval";
import type { AdvanceResult, ChallengeDecision, GitCommitAction, OperatorChallenge, OperatorStepDetail, OperatorWorkflow, WorkflowRun, WorkflowStep } from "@/lib/api/workflow-types";

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
  const [gitActions, setGitActions] = useState<GitCommitAction[]>([]);
  const [commitMessage, setCommitMessage] = useState("");
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
  useEffect(() => { if (!activeRunId) return; void fetch(`/api/workflows/${activeRunId}/git-commit-actions`, { cache: "no-store" }).then(async (response) => response.ok ? setGitActions(await response.json() as GitCommitAction[]) : undefined); }, [activeRunId]);
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
  async function prepareCommit() { if (!activeRunId || !commitMessage.trim() || busy) return; setBusy(true); setError(null); try { const response = await fetch(`/api/workflows/${activeRunId}/git-commit-actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ commit_message: commitMessage.trim() }) }); const value = await response.json() as GitCommitAction & { message?: string }; if (!response.ok) throw new Error(value.message || "Commit preparation failed."); setGitActions((actions) => [...actions, value]); } catch (cause) { setError(cause instanceof Error ? cause.message : "Commit preparation failed."); } finally { setBusy(false); } }
  return <div className="operator-stack"><section className="workflow-card" aria-labelledby="workflow-title"><div className="workflow-card-header"><div><p className="eyebrow">Development workflow · v{plan.version}</p><h2 id="workflow-title">{plan.title}</h2><p>{plan.summary}</p></div><div className="workflow-status-stack"><StatusBadge tone={runTones[run.status]}>{humanize(run.status)}</StatusBadge>{pendingChallenge ? <StatusBadge tone="neutral">Waiting for human</StatusBadge> : null}</div></div><div className="workflow-control"><div><strong>{controlTitle}</strong><span>One click sends exactly one bodyless Orchestrator advance request.</span></div><button className="primary-button" onClick={advance} disabled={busy || !canAdvance(run)}>{busy ? "Request in progress…" : canAdvance(run) ? "Run next step" : "No advance available"}</button></div>{workflow.qa_verdict ? <div className={`qa-verdict qa-verdict-${workflow.qa_verdict.toLowerCase()}`}><span>Final QA verdict</span><strong>{humanize(workflow.qa_verdict)}</strong></div> : null}{run.status === "COMPLETED" ? <section className="challenge-panel" aria-label="Local Git commit"><div><p className="eyebrow">Local Git commit</p><h4>Prepare exact changeset</h4><p>Policy requires a separate human approval. Only validated workflow mutations are included.</p></div><label>Commit message<input maxLength={200} value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} /></label><button className="primary-button" disabled={busy || !commitMessage.trim()} onClick={() => void prepareCommit()}>Prepare commit preview</button>{gitActions.map((action) => <div key={action.id}><p>{action.branch_ref} · {action.prepared_head_sha.slice(0, 12)} · {action.prepared_paths.map((item) => item.path).join(", ")}</p><pre>{action.preview.diff}</pre><p>Fingerprint: {action.action_fingerprint.slice(0, 12)} · Policy: Require confirmation · {humanize(action.status)}</p>{action.resulting_commit_sha ? <p>Committed: {action.resulting_commit_sha}</p> : null}{action.failure_code ? <InlineError>{humanize(action.failure_code)}</InlineError> : null}<GitApproval action={action} /></div>)}</section> : null}{error ? <InlineError>{error}</InlineError> : null}{lastResult ? <ResultBanner result={lastResult} /> : null}<ol className="workflow-steps">{orderedSteps.map((step) => { const stepRun = run.step_runs.find((item) => item.workflow_step_id === step.id); const detail = workflow.step_details.find((item) => item.workflow_step_run_id === stepRun?.id); return <WorkflowStepCard key={step.id} step={step} stepRun={stepRun} detail={detail} busy={busy} onResolve={resolveChallenge} />; })}</ol></section><ActivityFeed projectId={projectId} taskId={taskId} workflowRunId={run.id} onWorkflowEvent={handleWorkflowEvent} /></div>;
}

function GitApproval({ action }: Readonly<{ action: GitCommitAction }>) { const [busy, setBusy] = useState(false); if (action.status !== "PENDING_APPROVAL" || !action.approval_request_id) return null; async function decide(decision: "approve" | "reject") { setBusy(true); try { await fetch(`/api/approvals/${action.approval_request_id}/${decision}`, { method: "POST" }); window.location.reload(); } finally { setBusy(false); } } return <div className="challenge-actions"><button className="primary-button" disabled={busy} onClick={() => void decide("approve")}>Approve exact commit</button><button className="danger-button" disabled={busy} onClick={() => void decide("reject")}>Reject</button></div>; }

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
  return <div className="execution-metadata"><div className="execution-heading"><span>Execution metadata</span><strong>{humanize(agent.status)}</strong></div>{agent.model_runs.length === 0 ? <p>No provider invocation was recorded for this AgentRun.</p> : agent.model_runs.map((model) => <dl className="model-metadata" key={model.id}><div><dt>Provider / model</dt><dd>{model.provider_id} / {model.provider_model_id}</dd></div><div><dt>Target</dt><dd>{model.execution_target_class ? humanize(model.execution_target_class) : "Unavailable"}</dd></div><div><dt>ModelRun</dt><dd>{humanize(model.status)}</dd></div><div><dt>Tokens</dt><dd>{model.total_tokens ?? "—"} total{model.input_tokens !== null && model.output_tokens !== null ? ` (${model.input_tokens} in / ${model.output_tokens} out)` : ""}</dd></div><div><dt>Duration</dt><dd>{model.duration_ms === null ? "—" : `${model.duration_ms} ms`}</dd></div><div><dt>Attempt</dt><dd>{humanize(model.recovery_attempt_kind)} · {model.recovery_attempt_index}</dd></div>{model.failure_code ? <div><dt>Reason</dt><dd>{humanize(model.failure_code)}</dd></div> : null}</dl>)}{agent.tool_calls.map((tool) => <div key={tool.id}><dl className="model-metadata"><div><dt>Trusted tool</dt><dd>{tool.tool_name}</dd></div><div><dt>Status</dt><dd>{humanize(tool.status)}</dd></div><div><dt>Policy</dt><dd>{tool.policy_effect ? humanize(tool.policy_effect) : "Not evaluated"}</dd></div><div><dt>Target</dt><dd>{humanize(tool.execution_target_class)} · {tool.target_path || "Read only"}</dd></div><div><dt>Duration</dt><dd>{tool.duration_ms === null ? "—" : `${tool.duration_ms} ms`}</dd></div>{tool.approval_request_id ? <div><dt>ApprovalRequest</dt><dd title={tool.approval_request_id}>{tool.approval_request_id.slice(0, 8)} · exact one-action scope</dd></div> : null}{tool.failure_code ? <div><dt>Reason</dt><dd>{humanize(tool.failure_code)}</dd></div> : null}</dl>{tool.mutation_fingerprint ? <MutationApprovalPanel tool={tool} /> : null}</div>)}</div>;
}

function MutationApprovalPanel({ tool }: Readonly<{ tool: NonNullable<OperatorStepDetail["agent_run"]>["tool_calls"][number] }>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fingerprint = tool.mutation_fingerprint;
  if (fingerprint === null) return null;
  const canDecide = mutationApprovalState(tool) === "PENDING";
  async function decide(decision: "approve" | "reject") {
    if (!tool.approval_request_id || busy) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/approvals/${tool.approval_request_id}/${decision}`, { method: "POST" });
      const value = await response.json() as { message?: string };
      if (!response.ok) throw new Error(value.message || "The approval decision could not be recorded.");
      window.location.reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The approval decision could not be recorded."); }
    finally { setBusy(false); }
  }
  return <section className="challenge-panel" aria-label="Workspace mutation approval"><div><p className="eyebrow">Mutation preview</p><h4>{tool.target_path || "Confined workspace file"}</h4><p>Policy: {humanize(tool.policy_effect || "REQUIRE_CONFIRMATION")}. Status: {humanize(tool.status)}.</p></div><dl><div><dt>Fingerprint</dt><dd title={fingerprint}>{fingerprint.slice(0, 12)}</dd></div><div><dt>Line count</dt><dd>{tool.before_lines ?? "—"} → {tool.after_lines ?? "—"}</dd></div></dl><pre>{mutationPreviewLabel(tool)}</pre>{tool.diff_truncated ? <p className="inline-error">The mutation cannot be approved because its meaningful diff is truncated.</p> : null}{error ? <InlineError>{error}</InlineError> : null}{canDecide ? <div className="challenge-actions"><button className="primary-button" disabled={busy} onClick={() => void decide("approve")}>{busy ? "Recording decision…" : "Approve exact mutation"}</button><button className="danger-button" disabled={busy} onClick={() => void decide("reject")}>Reject</button></div> : null}</section>;
}

function ChallengePanel({ challenge, stepRunId, busy, onResolve }: Readonly<{ challenge: OperatorChallenge; stepRunId: string; busy: boolean; onResolve: (stepRunId: string, decision: ChallengeDecision, reason: string | null) => Promise<void> }>) {
  const [reason, setReason] = useState("");
  const informed = canResolveChallenge(challenge);
  const decisions = informed ? challengeDecisions(challenge.challenge_level) : [];
  return <div className="challenge-panel" role="alert"><div><p className="eyebrow">Agent result review</p><h4>Human decision required</h4><p>This is an Agent challenge, not a Policy ApprovalRequest. Workflow state remains server-authoritative.</p></div><dl><div><dt>Challenge</dt><dd>{humanize(challenge.challenge_level)}</dd></div>{challenge.qa_verdict ? <div><dt>QA verdict</dt><dd>{humanize(challenge.qa_verdict)}</dd></div> : null}</dl>{challenge.safe_review_summary ? <QAReviewSummaryPanel summary={challenge.safe_review_summary} /> : challenge.review_summary_status === "MISSING" ? <InlineError>Safe review details are unavailable for this historical QA result. No informed decision can be submitted.</InlineError> : null}{informed ? <><label>Decision reason <span>(optional, max 500 characters)</span><textarea maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label><div className="challenge-actions">{decisions.map((decision) => <button key={decision} className={decision === "REJECT_RESULT" ? "danger-button" : "primary-button"} disabled={busy} onClick={() => void onResolve(stepRunId, decision, reason.trim() || null)}>{busy ? "Decision in progress…" : humanize(decision)}</button>)}</div></> : null}{challenge.challenge_level === "BLOCK_RECOMMENDED" ? <p className="challenge-note">BLOCK_RECOMMENDED cannot be accepted in V1.</p> : null}</div>;
}

function QAReviewSummaryPanel({ summary }: Readonly<{ summary: NonNullable<OperatorChallenge["safe_review_summary"]> }>) {
  return <section aria-label="Safe QA review summary"><h5>Validated QA review summary</h5><p>{summary.validation_summary}</p><p><strong>Review reason:</strong> {summary.challenge_reason}</p>{summary.suggested_action ? <p><strong>Suggested action:</strong> {summary.suggested_action}</p> : null}<h5>Acceptance evidence</h5><ul>{summary.acceptance_results.map((item) => <li key={item.criterion_id}><strong>{humanize(item.status)} · {humanize(item.criterion_id)}</strong><p>{item.rationale}</p>{item.evidence_references.length ? <small>Evidence: {item.evidence_references.join(", ")}</small> : null}</li>)}</ul><h5>Warnings</h5>{summary.warnings.length ? <ul>{summary.warnings.map((item, index) => <li key={`${item.category}-${index}`}><strong>{humanize(item.category)}:</strong> {item.message}</li>)}</ul> : <p>None reported.</p>}<h5>Recommendations</h5>{summary.recommendations.length ? <ul>{summary.recommendations.map((item, index) => <li key={`${item.category}-${index}`}><strong>{humanize(item.category)}:</strong> {item.message}</li>)}</ul> : <p>None reported.</p>}<h5>Defects and concerns</h5>{summary.concerns.length ? <ul>{summary.concerns.map((item) => <li key={item.defect_key}><strong>{humanize(item.severity)} · {item.title}</strong><p>{item.description}</p><p>Remediation: {item.remediation_summary}</p></li>)}</ul> : <p>None reported.</p>}</section>;
}

function reasonText(reason: string | null, challenge: AdvanceResult["challenge_level"]) { const reasons: Record<string, string> = { agent_challenge: "The active Agent result requires an explicit human decision.", step_requires_intervention: "The current step needs human review before execution can continue.", manual_review_required: "This step is waiting for a human review.", no_ready_step: "No step is currently runnable.", workflow_cancelled: "The workflow was cancelled by the governing system.", workflow_failed: "The governing workflow marked this run as failed.", agent_assignment_required: "An approved agent assignment is required before this step can run.", qa_failed: "QA returned FAIL; the workflow cannot complete successfully.", qa_inconclusive: "QA returned INCONCLUSIVE; the workflow cannot complete successfully.", agent_challenge_rejected: "The operator rejected the challenged Agent result." }; return reason ? reasons[reason] || (reason.includes("failed") ? "The workflow reported a failure for this step." : `Server reason: ${humanize(reason)}`) : challenge && challenge !== "NONE" ? `Challenge signal: ${humanize(challenge)}.` : "The server accepted the operation and returned the current state."; }
