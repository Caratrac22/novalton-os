"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";

type Item = { topic: string; value: string; provenance: "USER" | "MODEL_PROPOSAL" | "INFERENCE"; state: "PROPOSED" | "CONFIRMED" | "CONFLICT" | "OPEN" };
type Version = { version: number; source: string; document: { summary: string; items: Item[] }; created_at: string };
type Plan = { id: string; source_version: number; status: string; document: { objective: string; steps: string[]; unresolved: Item[]; budget: string; origin: string }; decided_at: string | null };

export function SpecificationEditor({ projectId, conversationId }: { projectId: string; conversationId: string }) {
  const base = `/api/projects/${projectId}/conversations/${conversationId}/specifications`;
  const [versions, setVersions] = useState<Version[]>([]);
  const [summary, setSummary] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [view, setView] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [plans, setPlans] = useState<Plan[]>([]);
  const refresh = useCallback(async () => {
    const [response, planResponse] = await Promise.all([fetch(base, { cache: "no-store" }), fetch(base.replace(/\/specifications$/, "/plans"), { cache: "no-store" })]);
    if (!response.ok || !planResponse.ok) throw new Error("Cahier des charges indisponible ou accès retiré.");
    const data = await response.json() as { items: Version[] };
    const planData = await planResponse.json() as { items: Plan[] };
    setVersions(data.items); setSummary(data.items[0]?.document.summary ?? "");
    setItems(data.items[0]?.document.items ?? []); setView(null); setPlans(planData.items);
  }, [base]);
  useEffect(() => { void Promise.resolve().then(refresh).catch((cause: Error) => setError(cause.message)); }, [refresh]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch(base, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: versions[0]?.version ?? 0, summary, items }) });
      if (!response.ok) throw new Error(response.status === 409 ? "Le cahier a changé. Rechargez-le avant de modifier." : "Enregistrement refusé.");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function planAction(action: "PREPARE" | "READY_FOR_REVIEW" | "APPROVED" | "REJECTED" | "NEEDS_CHANGES") {
    setBusy(true); setError("");
    const plan = plans[0];
    const target = base.replace(/\/specifications$/, "/plans");
    try {
      const response = await fetch(action === "PREPARE" ? target : `${target}/${plan.id}/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "PREPARE" ? { expected_specification_version: versions[0]?.version } : { decision: action }),
      });
      if (!response.ok) throw new Error(response.status === 409 ? "Plan obsolète ou points à résoudre : rechargez et vérifiez le cahier." : "Action refusée.");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  const displayed = view === null ? null : versions.find((version) => version.version === view);
  return <section className="record-card" aria-label="Cahier des charges">
    <h2>Cahier des charges</h2><p className="section-note">Les propositions du modèle restent à confirmer. Chaque correction crée une version conservée.</p>
    <label htmlFor="spec-version">Version consultée</label>
    <select id="spec-version" value={view ?? "latest"} onChange={(event) => setView(event.target.value === "latest" ? null : Number(event.target.value))}>
      <option value="latest">Actuelle {versions[0] ? `· v${versions[0].version}` : "· aucun contenu"}</option>
      {versions.map((version) => <option key={version.version} value={version.version}>Version {version.version} · {version.source}</option>)}
    </select>
    {displayed ? <div><p>{displayed.document.summary}</p><ul>{displayed.document.items.map((item, index) => <li key={index}>{item.topic} : {item.value} ({item.state})</li>)}</ul></div> :
      <form className="workspace-form" onSubmit={save}>
        <label htmlFor="spec-summary">Résumé</label><textarea id="spec-summary" value={summary} maxLength={3000} rows={3} onChange={(event) => setSummary(event.target.value)} />
        <h3>Informations retenues</h3>
        {items.map((item, index) => <div key={index} className="workspace-form">
          <label htmlFor={`spec-value-${index}`}>{item.topic} · {item.provenance === "MODEL_PROPOSAL" ? "Proposition IA" : "Saisie humaine"}</label>
          <input id={`spec-value-${index}`} value={item.value} maxLength={2000} onChange={(event) => setItems((old) => old.map((entry, position) => position === index ? { ...entry, value: event.target.value, provenance: "USER" } : entry))} />
          <select aria-label={`État de ${item.topic}`} value={item.state} onChange={(event) => setItems((old) => old.map((entry, position) => position === index ? { ...entry, state: event.target.value as Item["state"], provenance: "USER" } : entry))}><option value="PROPOSED">À confirmer</option><option value="CONFIRMED">Confirmé</option><option value="CONFLICT">Contradiction</option><option value="OPEN">Question ouverte</option></select>
          <button type="button" onClick={() => setItems((old) => old.filter((_, position) => position !== index))}>Retirer cette information</button>
        </div>)}
        <button type="button" disabled={items.length >= 100} onClick={() => setItems((old) => [...old, { topic: "detail", value: "", provenance: "USER", state: "OPEN" }])}>Ajouter une information</button>
        <button disabled={busy}>{busy ? "Enregistrement…" : "Enregistrer une nouvelle version"}</button>
      </form>}
    <button type="button" onClick={() => void refresh().catch(() => setError("Actualisation impossible."))}>Actualiser le cahier</button>
    <section aria-label="Plan de projet"><h3>Plan et décision humaine</h3>
      {plans[0] ? <><p>Version du cahier : {plans[0].source_version} · état : {plans[0].status}</p><p>{plans[0].document.objective}</p><ol>{plans[0].document.steps.map((step) => <li key={step}>{step}</li>)}</ol><p>{plans[0].document.budget}</p><p className="section-note">{plans[0].document.origin} Aucun agent ne démarre après l’approbation.</p>
        {plans[0].status === "DRAFT" && <button type="button" disabled={busy} onClick={() => void planAction("READY_FOR_REVIEW")}>Soumettre à la revue</button>}
        {plans[0].status === "READY_FOR_REVIEW" && <><button type="button" disabled={busy} onClick={() => void planAction("APPROVED")}>Approuver ce plan</button><button type="button" disabled={busy} onClick={() => void planAction("NEEDS_CHANGES")}>Demander des changements</button><button type="button" disabled={busy} onClick={() => void planAction("REJECTED")}>Rejeter</button></>}
        {plans[0].decided_at && <p>Décision enregistrée le {new Date(plans[0].decided_at).toLocaleString("fr-FR")}.</p>}
      </> : <p>Aucun plan préparé pour ce cahier.</p>}
      {versions[0] && (!plans[0] || plans[0].source_version !== versions[0].version) && <button type="button" disabled={busy} onClick={() => void planAction("PREPARE")}>Préparer un brouillon depuis la version {versions[0].version}</button>}
    </section>
    {error && <p role="alert">{error}</p>}
  </section>;
}
