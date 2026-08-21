"use client";
import { useState } from "react";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { humanize } from "@/lib/format";
import type { AdvanceResult, DevelopmentWorkflow, WorkflowPlan, WorkflowRun, WorkflowStep } from "@/lib/api/workflow-types";

type TaskWorkspaceProps = Readonly<{ projectId: string; taskId: string; taskTitle: string; initialRun: WorkflowRun | null; initialPlan: WorkflowPlan | null }>;
const stepRoles: Record<string, string> = { manager_plan: "Developer Manager", developer_execute: "Developer Worker", qa_validate: "QA Worker" };
const stepDescriptions: Record<string, string> = { manager_plan: "Shapes the bounded development assignment.", developer_execute: "Carries out the governed development assignment.", qa_validate: "Checks the result against the acceptance criteria." };
const runTones: Record<string, StatusTone> = { CREATED: "neutral", RUNNING: "positive", COMPLETED: "positive", FAILED: "negative", CANCELLED: "negative" };
const stepTones: Record<string, StatusTone> = { PENDING: "neutral", READY: "neutral", RUNNING: "positive", COMPLETED: "positive", FAILED: "negative", CANCELLED: "negative" };

export function TaskWorkspace({ projectId, taskId, taskTitle, initialRun, initialPlan }: TaskWorkspaceProps) {
  const [workflow, setWorkflow] = useState<DevelopmentWorkflow | null>(initialRun && initialPlan ? { workflow_run: initialRun, workflow_plan: initialPlan } : null);
  const [objective, setObjective] = useState("");
  const [criteria, setCriteria] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<AdvanceResult | null>(null);

  async function createWorkflow(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    const acceptanceCriteria = criteria.split("\n").map((item) => item.trim()).filter(Boolean);
    try {
      const response = await fetch("/api/workflows/development", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, taskId, objective: objective.trim(), acceptanceCriteria }) });
      const value = await response.json() as DevelopmentWorkflow & { message?: string };
      if (!response.ok) throw new Error(value.message || "The development workflow could not be created.");
      setWorkflow(value); setObjective(""); setCriteria("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The development workflow could not be created."); }
    finally { setBusy(false); }
  }

  async function advance() {
    if (!workflow || busy || !canAdvance(workflow.workflow_run)) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflow.workflow_run.id}/advance`, { method: "POST" });
      const result = await response.json() as AdvanceResult & { message?: string };
      if (!response.ok) throw new Error(result.message || "The workflow could not be advanced.");
      const stateResponse = await fetch(`/api/workflows/${workflow.workflow_run.id}`, { cache: "no-store" });
      const state = await stateResponse.json() as WorkflowRun & { message?: string };
      if (!stateResponse.ok) throw new Error(state.message || "The workflow result was recorded, but its current state is unavailable.");
      setLastResult(result); setWorkflow({ ...workflow, workflow_run: state });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The workflow could not be advanced."); }
    finally { setBusy(false); }
  }

  if (!workflow) return <section className="workflow-card" aria-labelledby="workflow-create-title"><div className="workflow-card-header"><div><p className="eyebrow">Governed execution</p><h2 id="workflow-create-title">Create development workflow</h2><p>Start the fixed Manager → Developer Worker → QA sequence for this task. Each Advance action processes at most one step.</p></div></div><form className="workflow-form" onSubmit={createWorkflow}><label>Objective<textarea required maxLength={1500} value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={`What should be delivered for “${taskTitle}”?`} /></label><label>Acceptance criteria <span>(one per line)</span><textarea required value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder="The result meets the task requirements\nThe change is ready for QA" /></label>{error ? <InlineError>{error}</InlineError> : null}<button className="primary-button" disabled={busy}>{busy ? "Creating workflow…" : "Create workflow"}</button></form></section>;

  const { workflow_plan: plan, workflow_run: run } = workflow;
  const current = plan.steps.find((step) => run.step_runs.find((item) => item.workflow_step_id === step.id)?.status === "READY");
  return <section className="workflow-card" aria-labelledby="workflow-title"><div className="workflow-card-header"><div><p className="eyebrow">Development workflow · v{plan.version}</p><h2 id="workflow-title">{plan.title}</h2><p>{plan.summary}</p></div><StatusBadge tone={runTones[run.status]}>{humanize(run.status)}</StatusBadge></div><div className="workflow-control"><div><strong>{run.status === "COMPLETED" ? "Workflow complete" : run.status === "FAILED" ? "Workflow failed" : current ? `Next step: ${stepRoles[current.step_key] || humanize(current.step_key)}` : "Waiting for an operator decision"}</strong><span>One Advance action runs one server-authorized step.</span></div><button className="primary-button" onClick={advance} disabled={busy || !canAdvance(run)}>{busy ? "Advancing…" : canAdvance(run) ? "Advance one step" : "No advance available"}</button></div>{error ? <InlineError>{error}</InlineError> : null}{lastResult ? <ResultBanner result={lastResult} /> : null}<ol className="workflow-steps">{plan.steps.sort((a, b) => a.position - b.position).map((step) => <WorkflowStepCard key={step.id} step={step} stepRun={run.step_runs.find((item) => item.workflow_step_id === step.id)} />)}</ol></section>;
}

function canAdvance(run: WorkflowRun) { return (run.status === "CREATED" || run.status === "RUNNING") && run.step_runs.some((step) => step.status === "READY"); }
function InlineError({ children }: Readonly<{ children: React.ReactNode }>) { return <p className="inline-error" role="alert">{children}</p>; }
function ResultBanner({ result }: Readonly<{ result: AdvanceResult }>) { const waiting = result.outcome === "WAITING_FOR_HUMAN"; return <div className={`workflow-result ${waiting ? "is-waiting" : result.outcome.includes("FAILED") ? "is-failed" : ""}`} role="status"><strong>{waiting ? "Human intervention required" : humanize(result.outcome)}</strong><span>{reasonText(result.reason_code, result.challenge_level)}</span></div>; }
function WorkflowStepCard({ step, stepRun }: Readonly<{ step: WorkflowStep; stepRun?: WorkflowRun["step_runs"][number] }>) { const status = stepRun?.status || "PENDING"; return <li className={`workflow-step workflow-step-${status.toLowerCase()}`}><div className="workflow-step-index">{step.position + 1}</div><div className="workflow-step-content"><div className="workflow-step-heading"><div><span className="workflow-role">{stepRoles[step.step_key] || humanize(step.step_key)}</span><h3>{step.title}</h3></div><StatusBadge tone={stepTones[status]}>{humanize(status)}</StatusBadge></div><p>{stepDescriptions[step.step_key] || "Governed workflow step."}</p>{stepRun?.failure_code ? <p className="workflow-reason">{reasonText(stepRun.failure_code, null)}</p> : null}</div></li>; }
function reasonText(reason: string | null, challenge: AdvanceResult["challenge_level"]) { const reasons: Record<string, string> = { step_requires_intervention: "The current step needs human review before execution can continue.", manual_review_required: "This step is waiting for a human review.", no_ready_step: "No step is currently runnable.", workflow_cancelled: "The workflow was cancelled by the governing system.", workflow_failed: "The governing workflow marked this run as failed.", agent_assignment_required: "An approved agent assignment is required before this step can run." }; return reason ? reasons[reason] || (reason.includes("failed") ? "The workflow reported a failure for this step." : `Server reason: ${humanize(reason)}`) : challenge && challenge !== "NONE" ? `Challenge signal: ${humanize(challenge)}.` : "The server accepted the advance and returned the current state."; }
