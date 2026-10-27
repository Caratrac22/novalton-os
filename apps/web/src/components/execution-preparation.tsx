"use client";
import { useEffect, useRef, useState } from "react";

type Task = { id: string; title: string; status: string };
type Proposal = { id: string; status: string; document: {
  steps: { key: string; depends_on: string[]; capability: string }[];
  diagnostics: string[]; required_permissions: string[]; cost: string; environment: string;
} };
type Preflight = { ready_for_simulation: boolean; ready_for_launch: boolean; diagnostics: string[]; external_effects: boolean };
type LaunchDecision = { id: string; expires_at: string; revoked_at: string | null; workflow_created: boolean; workflow_run_id: string | null };
type LaunchStatus = { dispatch_id: string | null; dispatch_status: string | null; stop_reason: string | null; workflow_status: string | null; steps: { step_key: string; status: string }[]; qa_verdict: string | null };

const diagnosticLabels: Record<string, string> = {
  plan_obsolete_or_not_approved: "Le plan a changé ou son approbation n’est plus valable.",
  project_or_task_unavailable: "Le projet ou la tâche n’est plus disponible.",
  task_not_runnable: "Cette tâche n’est pas prête à être exécutée.",
  trusted_agents_unavailable: "Les définitions approuvées des agents ne sont pas disponibles.",
  dispatch_inactive: "Le dispatch est désactivé pour cet espace de travail.",
  operator_permissions_missing: "Les autorisations nécessaires manquent à votre compte.",
  model_and_environment_unverified: "Le modèle et l’environnement de test doivent être vérifiés.",
  financial_authorization_unverified: "La politique financière applicable n’est pas vérifiée.",
  separate_human_launch_authorization_missing: "Une décision humaine distincte de lancement est requise.",
};

export function ExecutionPreparation({ projectId, conversationId, planId }: {
  projectId: string; conversationId: string; planId: string;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [modelId, setModelId] = useState("");
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [decision, setDecision] = useState<LaunchDecision | null>(null);
  const [launchStatus, setLaunchStatus] = useState<LaunchStatus | null>(null);
  const [launchConfirmed, setLaunchConfirmed] = useState(false);
  const workflowRequest = useRef<string | null>(null);
  const dispatchRequest = useRef<string | null>(null);
  const base = `/api/projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations`;
  const launchBase = proposal && decision ? `${base}/${proposal.id}/launch-authorizations/${decision.id}` : null;
  useEffect(() => {
    if (!launchBase || !decision?.workflow_created) return;
    let current = true;
    const refresh = async () => {
      try {
        const response = await fetch(`${launchBase}/dispatch`, { cache: "no-store" });
        if (!response.ok) throw new Error("Suivi indisponible ou accès retiré.");
        if (current) setLaunchStatus(await response.json() as LaunchStatus);
      } catch { if (current) setError("Suivi indisponible ou accès retiré."); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { current = false; window.clearInterval(timer); };
  }, [launchBase, decision?.workflow_created]);
  useEffect(() => {
    let current = true;
    void fetch(`/api/projects/${projectId}/tasks`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Tâches indisponibles ou accès retiré.");
        const data = await response.json() as { items: Task[] };
        if (current) setTasks(data.items);
      }).catch((cause: Error) => { if (current) setError(cause.message); });
    return () => { current = false; };
  }, [projectId]);
  async function prepare() {
    setBusy(true); setError(""); setProposal(null); setPreflight(null); setDecision(null); setLaunchStatus(null);
    workflowRequest.current = null; dispatchRequest.current = null;
    try {
      const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }) });
      if (!response.ok) throw new Error(response.status === 409 ? "Plan obsolète ou non approuvé." : "Préparation refusée.");
      setProposal(await response.json() as Proposal);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function simulate() {
    if (!proposal) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/${proposal.id}/preflight`, { cache: "no-store" });
      if (!response.ok) throw new Error("Préflight indisponible ou accès retiré.");
      const data = await response.json() as { preflight: Preflight };
      setPreflight(data.preflight);
    } catch (cause) { setProposal(null); setPreflight(null); setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function authorizeTest() {
    if (!proposal || !preflight?.ready_for_simulation || !modelId.trim() || !password || !confirmed) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/${proposal.id}/launch-authorizations`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation: "AUTHORIZE_DISPOSABLE_TEST_LAUNCH", request_id: crypto.randomUUID(),
          environment: "DISPOSABLE_TEST", provider_id: "local", model_id: modelId.trim(),
          max_model_calls: 3, max_duration_seconds: 180, current_password: password,
        }),
      });
      if (!response.ok) throw new Error("Décision refusée : vérifiez le compte, les grants, la tâche et la fraîcheur du plan.");
      setDecision(await response.json() as LaunchDecision);
      setPassword(""); setConfirmed(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function revokeTest() {
    if (!proposal || !decision || !password) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/${proposal.id}/launch-authorizations/${decision.id}/revoke`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: password }),
      });
      if (!response.ok) throw new Error("Révocation refusée ou session expirée.");
      setDecision(await response.json() as LaunchDecision); setPassword("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function createTestWorkflow() {
    if (!launchBase || !decision || !password || decision.revoked_at || !launchConfirmed) return;
    setBusy(true); setError("");
    try {
      workflowRequest.current ??= crypto.randomUUID();
      const response = await fetch(`${launchBase}/workflow`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "CREATE_DISPOSABLE_TEST_WORKFLOW", request_id: workflowRequest.current, current_password: password }),
      });
      if (!response.ok) throw new Error("Création refusée : le plan, les grants ou le profil de test ont changé.");
      setDecision(await response.json() as LaunchDecision); setPassword(""); setLaunchConfirmed(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function dispatchTest() {
    if (!launchBase || !decision?.workflow_created || !password || decision.revoked_at || !launchConfirmed) return;
    setBusy(true); setError("");
    try {
      dispatchRequest.current ??= crypto.randomUUID();
      const response = await fetch(`${launchBase}/dispatch`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "ENQUEUE_DISPOSABLE_TEST_WORKFLOW", request_id: dispatchRequest.current, current_password: password }),
      });
      if (!response.ok) throw new Error("Lancement refusé : l’autorisation, le modèle local ou la capacité du worker n’est plus valable.");
      const queued = await response.json() as { dispatch_id: string; status: string };
      setLaunchStatus((old) => ({ dispatch_id: queued.dispatch_id, dispatch_status: queued.status,
        stop_reason: null, workflow_status: old?.workflow_status ?? "CREATED", steps: old?.steps ?? [], qa_verdict: null }));
      setPassword(""); setLaunchConfirmed(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  return <section className="execution-preparation" aria-label="Préparation de l’exécution">
    <h3>Préparer l’exécution</h3>
    <p>Le plan approuvé sert à construire une proposition à examiner. La préparation et la simulation ne lancent aucun agent.</p>
    <label htmlFor="execution-task">Tâche de ce projet</label>
    <select id="execution-task" value={taskId} onChange={(event) => { setTaskId(event.target.value); setProposal(null); setPreflight(null); setDecision(null); setLaunchStatus(null); }}>
      <option value="">Choisir une tâche existante</option>
      {tasks.map((task) => <option key={task.id} value={task.id}>{task.title} · {task.status}</option>)}
    </select>
    <button type="button" disabled={!taskId || busy} onClick={() => void prepare()}>Préparer l’exécution</button>
    {proposal && <div>
      <p>Proposition : {proposal.status} · environnement : {proposal.document.environment}</p>
      {proposal.document.steps.length > 0 && <ol>{proposal.document.steps.map((step) => <li key={step.key}>{step.key} · {step.capability} · prérequis : {step.depends_on.join(", ") || "aucun"}</li>)}</ol>}
      <p>Permissions à vérifier : {proposal.document.required_permissions.join(", ")}</p>
      <p>{proposal.document.cost}</p>
      {proposal.document.diagnostics.length > 0 && <ul>{proposal.document.diagnostics.map((item) => <li key={item}>{item}</li>)}</ul>}
      <button type="button" disabled={busy || proposal.status !== "PROPOSED"} onClick={() => void simulate()}>Simuler</button>
    </div>}
    {preflight && <div role="status">
      <p>Simulation sans effet externe : {preflight.ready_for_simulation ? "proposition lisible" : "bloquée"}.</p>
      <ul>{preflight.diagnostics.map((item) => <li key={item}>{diagnosticLabels[item] ?? item}</li>)}</ul>
    </div>}
    {proposal?.status === "PROPOSED" && preflight?.ready_for_simulation && <div>
      <h4>Autorisation distincte du test</h4>
      <p>Cette décision expire après dix minutes. Elle concerne uniquement un modèle local, trois appels au plus, une durée maximale de trois minutes et l’environnement jetable. Elle ne crée ni ne lance de workflow.</p>
      <label htmlFor="execution-model">Identifiant exact du modèle local</label>
      <input id="execution-model" value={modelId} maxLength={256} onChange={(event) => setModelId(event.target.value)} autoComplete="off" />
      <label htmlFor="execution-password">Mot de passe du compte local</label>
      <input id="execution-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
      {!decision && <>
        <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> J’autorise explicitement cette préparation de test jetable.</label>
        <button type="button" disabled={busy || !confirmed || !modelId.trim() || !password} onClick={() => void authorizeTest()}>Autoriser le test</button>
      </>}
      {decision && <div role="status">
        <p>Décision {decision.revoked_at ? "révoquée" : "enregistrée"} · expiration : {new Date(decision.expires_at).toLocaleString("fr-FR")} · workflow créé : {decision.workflow_created ? "oui" : "non"}.</p>
        {!decision.revoked_at && <button type="button" disabled={busy || !password} onClick={() => void revokeTest()}>Révoquer cette décision</button>}
        {!decision.revoked_at && !launchStatus?.dispatch_id && <>
          <label><input type="checkbox" checked={launchConfirmed} onChange={(event) => setLaunchConfirmed(event.target.checked)} /> Je confirme la création puis le lancement jetable sous cette autorisation.</label>
          {!decision.workflow_created ? <button type="button" disabled={busy || !password || !launchConfirmed} onClick={() => void createTestWorkflow()}>Créer le workflow de test</button>
            : <button type="button" disabled={busy || !password || !launchConfirmed} onClick={() => void dispatchTest()}>Lancer le test autorisé</button>}
        </>}
        {launchStatus && <div><p>Workflow : {launchStatus.workflow_status ?? "absent"} · dispatch : {launchStatus.dispatch_status ?? "absent"}.</p>
          {launchStatus.steps.length > 0 && <ol>{launchStatus.steps.map((step) => <li key={step.step_key}>{step.step_key} : {step.status}</li>)}</ol>}
          {launchStatus.qa_verdict && <p>Verdict QA : {launchStatus.qa_verdict}</p>}
          {launchStatus.stop_reason && <p>Arrêt : {launchStatus.stop_reason}</p>}
          {launchStatus.dispatch_id && <p>Preuve de dispatch : {launchStatus.dispatch_id}</p>}
        </div>}
      </div>}
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
