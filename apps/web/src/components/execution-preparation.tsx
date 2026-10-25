"use client";
import { useEffect, useState } from "react";

type Task = { id: string; title: string; status: string };
type Proposal = { id: string; status: string; document: {
  steps: { key: string; depends_on: string[]; capability: string }[];
  diagnostics: string[]; required_permissions: string[]; cost: string; environment: string;
} };
type Preflight = { ready_for_simulation: boolean; ready_for_launch: boolean; diagnostics: string[]; external_effects: boolean };

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
  const base = `/api/projects/${projectId}/conversations/${conversationId}/plans/${planId}/compilations`;
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
    setBusy(true); setError(""); setProposal(null); setPreflight(null);
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
  return <section className="execution-preparation" aria-label="Préparation de l’exécution">
    <h3>Préparer l’exécution</h3>
    <p>Le plan approuvé sert à construire une proposition à examiner. La préparation et la simulation ne lancent aucun agent.</p>
    <label htmlFor="execution-task">Tâche de ce projet</label>
    <select id="execution-task" value={taskId} onChange={(event) => { setTaskId(event.target.value); setProposal(null); setPreflight(null); }}>
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
    <button type="button" disabled aria-describedby="launch-unavailable">Autoriser le lancement</button>
    <p id="launch-unavailable">Lancement indisponible : autorisation humaine distincte, capacités, fournisseur et budget non vérifiés.</p>
    {error && <p role="alert">{error}</p>}
  </section>;
}
