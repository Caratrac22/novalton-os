"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityFeed } from "@/components/activity-feed";
import { GitHubPublication } from "@/components/github-publication";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { humanize } from "@/lib/format";
import { canAdvanceWorkflow, canResolveChallenge, challengeDecisions, challengeResolutionBody, orderedWorkflowSteps } from "@/lib/operator-controls";
import { mutationApprovalState, mutationPreviewLabel } from "@/lib/mutation-approval";
import type { AdvanceResult, ChallengeDecision, GitCommitAction, OperatorChallenge, OperatorStepDetail, OperatorWorkflow, WorkflowRun, WorkflowStep } from "@/lib/api/workflow-types";

type TaskWorkspaceProps = Readonly<{ projectId: string; taskId: string; taskTitle: string; initialWorkflow: OperatorWorkflow | null }>;
const stepRoles: Record<string, string> = { manager_plan: "Manager", developer_execute: "Développeur", qa_validate: "Contrôle qualité" };
const stepDescriptions: Record<string, string> = { manager_plan: "Prépare la mission de développement bornée.", developer_execute: "Réalise la mission sous contrôle.", qa_validate: "Vérifie le résultat selon les critères d’acceptation." };
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
      if (!response.ok) throw new Error(value.message || "État du workflow indisponible.");
      setWorkflow(value);
    } finally { refreshing.current = false; }
  }, []);
  const activeRunId = workflow?.workflow_run.id;
  useEffect(() => { if (!activeRunId) return; let active = true; void fetch(`/api/workflows/${activeRunId}/git-commit-actions`, { cache: "no-store" }).then(async (response) => {
    if (!response.ok) throw new Error("Historique Git indisponible.");
    const actions = await response.json() as GitCommitAction[];
    if (active) setGitActions(actions);
  }).catch(() => { if (active) setError("Historique des commits indisponible."); }); return () => { active = false; }; }, [activeRunId]);
  const handleWorkflowEvent = useCallback(() => { if (activeRunId) void refreshWorkflow(activeRunId).catch(() => setError("Actualisation du workflow indisponible.")); }, [activeRunId, refreshWorkflow]);

  async function createWorkflow(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    const acceptanceCriteria = criteria.split("\n").map((item) => item.trim()).filter(Boolean);
    try {
      const response = await fetch("/api/workflows/development", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ projectId, taskId, objective: objective.trim(), acceptanceCriteria }) });
      const value = await response.json() as { workflow_run?: { id?: string }; message?: string };
      if (!response.ok || !value.workflow_run?.id) throw new Error(value.message || "Impossible de créer le workflow.");
      await refreshWorkflow(value.workflow_run.id);
      setObjective(""); setCriteria("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible de créer le workflow."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  async function advance() {
    if (!workflow || operationInFlight.current || !canAdvance(workflow.workflow_run)) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflow.workflow_run.id}/advance`, { method: "POST" });
      const result = await response.json() as AdvanceResult & { message?: string };
      if (!response.ok) throw new Error(result.message || "Impossible d’avancer le workflow.");
      setLastResult(result);
      await refreshWorkflow(workflow.workflow_run.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible d’avancer le workflow."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  async function resolveChallenge(stepRunId: string, decision: ChallengeDecision, reason: string | null) {
    if (!workflow || operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/workflows/${workflow.workflow_run.id}/steps/${stepRunId}/challenge-resolution`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(challengeResolutionBody(decision, reason || "")) });
      const value = await response.json() as { message?: string };
      if (!response.ok) throw new Error(value.message || "Impossible d’enregistrer la décision.");
      setLastResult(null);
      await refreshWorkflow(workflow.workflow_run.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible d’enregistrer la décision."); }
    finally { operationInFlight.current = false; setBusy(false); }
  }

  if (!workflow) return <section className="workflow-card" aria-labelledby="workflow-create-title"><div className="workflow-card-header"><div><p className="eyebrow">Exécution gouvernée</p><h2 id="workflow-create-title">Créer un workflow de développement</h2><p>Lancez la séquence Manager → Développeur → QA. Chaque action traite au plus une étape autorisée par le serveur.</p></div></div><form className="workflow-form" onSubmit={createWorkflow}><label>Objectif<textarea required maxLength={1500} value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={`Que faut-il livrer pour « ${taskTitle} » ?`} /></label><label>Critères d’acceptation <span>(un par ligne, 24 au maximum)</span><textarea required value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder="Le résultat répond aux exigences\nLe changement est prêt pour le contrôle qualité" /></label>{error ? <InlineError>{error}</InlineError> : null}<button className="primary-button" disabled={busy}>{busy ? "Création du workflow…" : "Créer le workflow"}</button></form></section>;

  const { workflow_plan: plan, workflow_run: run } = workflow;
  const orderedSteps = orderedWorkflowSteps(plan.steps);
  const current = orderedSteps.find((step) => run.step_runs.find((item) => item.workflow_step_id === step.id)?.status === "READY");
  const pendingChallenge = workflow.step_details.find((detail) => detail.challenge?.decision === null)?.challenge;
  const controlTitle = run.status === "COMPLETED" ? "Workflow terminé" : run.status === "FAILED" ? "Échec du workflow" : pendingChallenge ? "Décision humaine requise" : current ? `Étape suivante : ${stepRoles[current.step_key] || humanize(current.step_key)}` : "Aucune étape exécutable";
  async function prepareCommit() { if (!activeRunId || !commitMessage.trim() || busy) return; setBusy(true); setError(null); try { const response = await fetch(`/api/workflows/${activeRunId}/git-commit-actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ commit_message: commitMessage.trim() }) }); const value = await response.json() as GitCommitAction & { message?: string }; if (!response.ok) throw new Error(value.message || "Préparation du commit impossible."); setGitActions((actions) => [...actions, value]); } catch (cause) { setError(cause instanceof Error ? cause.message : "Préparation du commit impossible."); } finally { setBusy(false); } }
  return <div className="operator-stack"><section className="workflow-card" aria-labelledby="workflow-title"><div className="workflow-card-header"><div><p className="eyebrow">Workflow de développement · v{plan.version}</p><h2 id="workflow-title">{plan.title}</h2><p>{plan.summary}</p></div><div className="workflow-status-stack"><StatusBadge tone={runTones[run.status]}>{humanize(run.status)}</StatusBadge>{pendingChallenge ? <StatusBadge tone="neutral">En attente d’une décision</StatusBadge> : null}</div></div><div className="workflow-control"><div><strong>{controlTitle}</strong><span>Chaque clic demande au serveur de traiter au plus une étape gouvernée.</span></div><button className="primary-button" onClick={advance} disabled={busy || !canAdvance(run)}>{busy ? "Demande en cours…" : canAdvance(run) ? "Exécuter l’étape suivante" : "Aucune action disponible"}</button></div>{workflow.qa_verdict ? <div className={`qa-verdict qa-verdict-${workflow.qa_verdict.toLowerCase()}`}><span>Verdict QA final</span><strong>{humanize(workflow.qa_verdict)}</strong></div> : null}{run.status === "COMPLETED" ? <section className="challenge-panel" aria-label="Commit Git local"><div><p className="eyebrow">Commit Git local</p><h4>Préparer les modifications exactes</h4><p>Une approbation humaine distincte est obligatoire. Seules les modifications validées sont incluses.</p></div><label>Message du commit<input maxLength={200} value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} /></label><button className="primary-button" disabled={busy || !commitMessage.trim()} onClick={() => void prepareCommit()}>Préparer l’aperçu du commit</button>{gitActions.map((action) => <div key={action.id}><p>{action.branch_ref} · {action.prepared_head_sha.slice(0, 12)} · {action.prepared_paths.map((item) => item.path).join(", ")}</p><pre>{action.preview.diff}</pre><p>Empreinte : {action.action_fingerprint.slice(0, 12)} · Politique : confirmation requise · {humanize(action.status)}</p>{action.resulting_commit_sha ? <p>Committed: {action.resulting_commit_sha}</p> : null}{action.failure_code ? <InlineError>{humanize(action.failure_code)}</InlineError> : null}<GitApproval action={action} /></div>)}</section> : null}{error ? <InlineError>{error}</InlineError> : null}{lastResult ? <ResultBanner result={lastResult} /> : null}<ol className="workflow-steps">{orderedSteps.map((step) => { const stepRun = run.step_runs.find((item) => item.workflow_step_id === step.id); const detail = workflow.step_details.find((item) => item.workflow_step_run_id === stepRun?.id); return <WorkflowStepCard key={step.id} step={step} stepRun={stepRun} detail={detail} busy={busy} onResolve={resolveChallenge} />; })}</ol></section><ActivityFeed projectId={projectId} taskId={taskId} workflowRunId={run.id} onWorkflowEvent={handleWorkflowEvent} /></div>;
}

function GitApproval({ action }: Readonly<{ action: GitCommitAction }>) { const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); async function decide(decision: "approve" | "reject") { if (!action.approval_request_id || busy) return; setBusy(true); setError(null); try { const response = await fetch(`/api/approvals/${action.approval_request_id}/${decision}`, { method: "POST" }); if (!response.ok) throw new Error("Décision refusée ou indisponible."); window.location.reload(); } catch { setError("Décision refusée ou indisponible. L’état du workflow n’a pas été modifié localement."); } finally { setBusy(false); } } return <>{action.status === "PENDING_APPROVAL" && action.approval_request_id ? <div className="challenge-actions"><button className="primary-button" disabled={busy} onClick={() => void decide("approve")}>Approuver le commit exact</button><button className="danger-button" disabled={busy} onClick={() => void decide("reject")}>Rejeter</button></div> : null}{error ? <InlineError>{error}</InlineError> : null}<GitHubPublication action={action} /></>; }

function canAdvance(run: WorkflowRun) { return canAdvanceWorkflow(run); }
function InlineError({ children }: Readonly<{ children: React.ReactNode }>) { return <p className="inline-error" role="alert">{children}</p>; }
function ResultBanner({ result }: Readonly<{ result: AdvanceResult }>) { const waiting = result.outcome === "WAITING_FOR_HUMAN"; return <div className={`workflow-result ${waiting ? "is-waiting" : result.outcome.includes("FAILED") ? "is-failed" : ""}`} role="status"><strong>{waiting ? "Intervention humaine requise" : humanize(result.outcome)}</strong><span>{reasonText(result.reason_code, result.challenge_level)}</span></div>; }

function WorkflowStepCard({ step, stepRun, detail, busy, onResolve }: Readonly<{ step: WorkflowStep; stepRun?: WorkflowRun["step_runs"][number]; detail?: OperatorStepDetail; busy: boolean; onResolve: (stepRunId: string, decision: ChallengeDecision, reason: string | null) => Promise<void> }>) {
  const status = stepRun?.status || "PENDING";
  return <li className={`workflow-step workflow-step-${status.toLowerCase()}`}><div className="workflow-step-index">{step.position + 1}</div><div className="workflow-step-content"><div className="workflow-step-heading"><div><span className="workflow-role">{stepRoles[step.step_key] || humanize(step.step_key)}</span><h3>{step.title}</h3></div><StatusBadge tone={stepTones[status]}>{humanize(status)}</StatusBadge></div><p>{stepDescriptions[step.step_key] || "Étape du workflow gouverné."}</p>{stepRun?.failure_code ? <p className="workflow-reason">{reasonText(stepRun.failure_code, null)}</p> : null}{detail?.agent_run ? <AgentMetadata detail={detail} /> : null}{detail?.challenge?.decision === null && stepRun ? <ChallengePanel challenge={detail.challenge} stepRunId={stepRun.id} busy={busy} onResolve={onResolve} /> : detail?.challenge?.decision ? <p className="challenge-resolved">Agent challenge resolved: {humanize(detail.challenge.decision)}</p> : null}</div></li>;
}

function AgentMetadata({ detail }: Readonly<{ detail: OperatorStepDetail }>) {
  const agent = detail.agent_run;
  if (!agent) return null;
  return <div className="execution-metadata"><div className="execution-heading"><span>Détails d’exécution</span><strong>{humanize(agent.status)}</strong></div>{agent.model_runs.length === 0 ? <p>Aucun appel fournisseur enregistré pour cet agent.</p> : agent.model_runs.map((model) => <dl className="model-metadata" key={model.id}><div><dt>Fournisseur / modèle</dt><dd>{model.provider_id} / {model.provider_model_id}</dd></div><div><dt>Cible</dt><dd>{model.execution_target_class ? humanize(model.execution_target_class) : "Indisponible"}</dd></div><div><dt>ModelRun</dt><dd>{humanize(model.status)}</dd></div><div><dt>Tokens</dt><dd>{model.total_tokens ?? "—"} total{model.input_tokens !== null && model.output_tokens !== null ? ` (${model.input_tokens} in / ${model.output_tokens} out)` : ""}</dd></div><div><dt>Durée</dt><dd>{model.duration_ms === null ? "—" : `${model.duration_ms} ms`}</dd></div><div><dt>Tentative</dt><dd>{humanize(model.recovery_attempt_kind)} · {model.recovery_attempt_index}</dd></div>{model.failure_code ? <div><dt>Motif</dt><dd>{humanize(model.failure_code)}</dd></div> : null}</dl>)}{agent.tool_calls.map((tool) => <div key={tool.id}><dl className="model-metadata"><div><dt>Outil contrôlé</dt><dd>{tool.tool_name}</dd></div><div><dt>État</dt><dd>{humanize(tool.status)}</dd></div><div><dt>Politique</dt><dd>{tool.policy_effect ? humanize(tool.policy_effect) : "Non évalué"}</dd></div><div><dt>Cible</dt><dd>{humanize(tool.execution_target_class)} · {tool.target_path || "Lecture seule"}</dd></div><div><dt>Durée</dt><dd>{tool.duration_ms === null ? "—" : `${tool.duration_ms} ms`}</dd></div>{tool.approval_request_id ? <div><dt>ApprovalRequest</dt><dd title={tool.approval_request_id}>{tool.approval_request_id.slice(0, 8)} · exact one-action scope</dd></div> : null}{tool.failure_code ? <div><dt>Motif</dt><dd>{humanize(tool.failure_code)}</dd></div> : null}</dl>{tool.verification ? <VerificationEvidence tool={tool} /> : null}{tool.mutation_fingerprint ? <MutationApprovalPanel tool={tool} /> : null}</div>)}</div>;
}

function VerificationEvidence({ tool }: Readonly<{ tool: NonNullable<OperatorStepDetail["agent_run"]>["tool_calls"][number] }>) {
  const result = tool.verification;
  if (!result) return null;
  return <section aria-label="Preuves de vérification">
    <p>Syntaxe Python backend · {humanize(result.state)} · {result.checked_files} fichiers vérifiés</p>
    <p>Code de sortie : {result.exit_code ?? "Indisponible"} · Espace : {tool.workspace_integrity ?? "Non vérifié"}</p>
    {result.failure_code ? <p>{humanize(result.failure_code)}</p> : null}
    <p>Preuve bornée · DONNÉES_NON_FIABLES{result.truncated ? " · Diagnostics tronqués" : ""}</p>
    <ul>{result.diagnostics.map((item) => <li key={item.path}>{item.path}: {humanize(item.code)}</li>)}</ul>
    <p>Empreinte source : {tool.verified_source_sha256}</p>
    <p>La vérification syntaxique n’exécute pas les tests et ne prouve pas le comportement.</p>
  </section>;
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
      if (!response.ok) throw new Error(value.message || "Impossible d’enregistrer la décision d’approbation.");
      window.location.reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible d’enregistrer la décision d’approbation."); }
    finally { setBusy(false); }
  }
  return <section className="challenge-panel" aria-label="Approbation de modification de l’espace"><div><p className="eyebrow">Aperçu de la modification</p><h4>{tool.target_path || "Fichier confiné de l’espace"}</h4><p>Politique : {humanize(tool.policy_effect || "REQUIRE_CONFIRMATION")}. État : {humanize(tool.status)}.</p></div><dl><div><dt>Empreinte</dt><dd title={fingerprint}>{fingerprint.slice(0, 12)}</dd></div><div><dt>Nombre de lignes</dt><dd>{tool.before_lines ?? "—"} → {tool.after_lines ?? "—"}</dd></div></dl><pre>{mutationPreviewLabel(tool)}</pre>{tool.diff_truncated ? <p className="inline-error">Impossible d’approuver : le diff utile est tronqué.</p> : null}{error ? <InlineError>{error}</InlineError> : null}{canDecide ? <div className="challenge-actions"><button className="primary-button" disabled={busy} onClick={() => void decide("approve")}>{busy ? "Enregistrement…" : "Approuver la modification exacte"}</button><button className="danger-button" disabled={busy} onClick={() => void decide("reject")}>Rejeter</button></div> : null}</section>;
}

function ChallengePanel({ challenge, stepRunId, busy, onResolve }: Readonly<{ challenge: OperatorChallenge; stepRunId: string; busy: boolean; onResolve: (stepRunId: string, decision: ChallengeDecision, reason: string | null) => Promise<void> }>) {
  const [reason, setReason] = useState("");
  const informed = canResolveChallenge(challenge);
  const decisions = informed ? challengeDecisions(challenge.challenge_level) : [];
  return <div className="challenge-panel" role="alert"><div><p className="eyebrow">Examen du résultat de l’agent</p><h4>Décision humaine requise</h4><p>Il s’agit d’un examen du résultat de l’agent. Le serveur garde l’autorité sur le workflow.</p></div><dl><div><dt>Challenge</dt><dd>{humanize(challenge.challenge_level)}</dd></div>{challenge.qa_verdict ? <div><dt>Verdict QA</dt><dd>{humanize(challenge.qa_verdict)}</dd></div> : null}</dl>{challenge.safe_review_summary ? <QAReviewSummaryPanel summary={challenge.safe_review_summary} /> : challenge.review_summary_status === "MISSING" ? <InlineError>Résumé sécurisé indisponible pour cet ancien résultat QA. Aucune décision éclairée ne peut être soumise.</InlineError> : null}{informed ? <><label>Motif de la décision <span>(facultatif, 500 caractères maximum)</span><textarea maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label><div className="challenge-actions">{decisions.map((decision) => <button key={decision} className={decision === "REJECT_RESULT" ? "danger-button" : "primary-button"} disabled={busy} onClick={() => void onResolve(stepRunId, decision, reason.trim() || null)}>{busy ? "Décision en cours…" : humanize(decision)}</button>)}</div></> : null}{challenge.challenge_level === "BLOCK_RECOMMENDED" ? <p className="challenge-note">Un résultat avec blocage recommandé ne peut pas être accepté en V1.</p> : null}</div>;
}

function QAReviewSummaryPanel({ summary }: Readonly<{ summary: NonNullable<OperatorChallenge["safe_review_summary"]> }>) {
  return <section aria-label="Résumé QA sécurisé"><h5>Résumé QA vérifié</h5><p>{summary.validation_summary}</p><p><strong>Motif de l’examen :</strong> {summary.challenge_reason}</p>{summary.suggested_action ? <p><strong>Action suggérée :</strong> {summary.suggested_action}</p> : null}<h5>Preuves d’acceptation</h5><ul>{summary.acceptance_results.map((item) => <li key={item.criterion_id}><strong>{humanize(item.status)} · {humanize(item.criterion_id)}</strong><p>{item.rationale}</p>{item.evidence_references.length ? <small>Preuves : {item.evidence_references.join(", ")}</small> : null}</li>)}</ul><h5>Avertissements</h5>{summary.warnings.length ? <ul>{summary.warnings.map((item, index) => <li key={`${item.category}-${index}`}><strong>{humanize(item.category)}:</strong> {item.message}</li>)}</ul> : <p>Aucun signalement.</p>}<h5>Recommandations</h5>{summary.recommendations.length ? <ul>{summary.recommendations.map((item, index) => <li key={`${item.category}-${index}`}><strong>{humanize(item.category)}:</strong> {item.message}</li>)}</ul> : <p>Aucun signalement.</p>}<h5>Défauts et réserves</h5>{summary.concerns.length ? <ul>{summary.concerns.map((item) => <li key={item.defect_key}><strong>{humanize(item.severity)} · {item.title}</strong><p>{item.description}</p><p>Correction : {item.remediation_summary}</p></li>)}</ul> : <p>Aucun signalement.</p>}</section>;
}

function reasonText(reason: string | null, challenge: AdvanceResult["challenge_level"]) { const reasons: Record<string, string> = { agent_challenge: "Le résultat de l’agent exige une décision humaine explicite.", step_requires_intervention: "L’étape doit être examinée avant de poursuivre.", manual_review_required: "Cette étape attend un examen humain.", no_ready_step: "Aucune étape ne peut être exécutée actuellement.", workflow_cancelled: "Le système a annulé le workflow.", workflow_failed: "Le workflow a signalé un échec.", agent_assignment_required: "Une affectation d’agent approuvée est nécessaire.", qa_failed: "Le QA a signalé un échec.", qa_inconclusive: "Le QA n’a pas pu conclure.", agent_challenge_rejected: "L’opérateur a rejeté le résultat contesté." }; return reason ? reasons[reason] || (reason.includes("failed") ? "Le workflow a signalé un échec pour cette étape." : `Motif du serveur : ${humanize(reason)}`) : challenge && challenge !== "NONE" ? `Signal d’examen : ${humanize(challenge)}.` : "Le serveur a accepté l’opération et renvoyé son état actuel."; }
