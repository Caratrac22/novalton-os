import { dispatchUpstream, parseDispatches } from "@/lib/api/dispatch";
import { isUuid } from "@/lib/api/scoped";
import { humanize } from "@/lib/format";
import { OperatorActions } from "./operator-actions";

export const dynamic = "force-dynamic";

type Detail = { workflow_plan?: { title?: string }; workflow_run?: { status?: string }; step_details?: Array<{ specialization_role?: string | null; agent_run?: { status?: string; model_runs?: Array<{ id?: string; status?: string; provider_model_id?: string }> } | null; challenge?: { challenge_level?: string; decision?: string | null } | null }> };
type Cost = { model_run_id: string; classification: string; catalog_priced_usage: string | null; reserved_estimated_exposure: string | null; provider_reported_cost: string | null; provider_report_exceeds_reservation: boolean; provider_billing_status: string };
type Attempt = { generation: number; outcome: string | null; reason_code: string | null };

export default async function OperatorDetail({ params }: { params: Promise<{ dispatchId: string }> }) {
  const { dispatchId } = await params;
  if (!isUuid(dispatchId)) return <p>Identifiant d’exécution invalide.</p>;
  const [requests, workflow, costs, attempts] = await Promise.all([
    dispatchUpstream("requests?limit=100"),
    dispatchUpstream(`requests/${dispatchId}/workflow`),
    dispatchUpstream(`requests/${dispatchId}/cost-evidence`),
    dispatchUpstream(`requests/${dispatchId}/attempts`),
  ]);
  if (!requests?.ok || !workflow?.ok || !costs?.ok || !attempts?.ok) return <p role="status">Données opérateur indisponibles ou accès révoqué.</p>;
  let list;
  try { list = parseDispatches(await requests.json()); } catch { return <p role="status">Réponse opérateur invalide.</p>; }
  const row = list.find((item) => item.id === dispatchId);
  if (!row) return <p>Exécution absente des 100 demandes chargées dans cet espace.</p>;
  const details = await workflow.json() as Detail;
  const evidence = await costs.json() as Cost[];
  const history = await attempts.json() as Attempt[];
  return <div className="page-stack operator-details">
    <section className="page-heading"><p className="eyebrow">Opérateur · {humanize(row.status)}</p><div><h1>{details.workflow_plan?.title ?? "Workflow"}</h1><p>{row.workflow_run_id} · {humanize(details.workflow_run?.status ?? "Inconnu")}</p></div></section>
    {row.stop_reason && <p role="status">Motif d’arrêt : {humanize(row.stop_reason)}</p>}
    <section><h2>Manager → Developer → QA</h2><ul>{details.step_details?.map((step, index) => <li key={index}>
      {humanize(step.specialization_role ?? "Étape")} · {humanize(step.agent_run?.status ?? "En attente")}
      {step.challenge && <strong> · Décision humaine {humanize(step.challenge.decision ?? "En attente")} ({humanize(step.challenge.challenge_level ?? "Inconnu")})</strong>}
      <ul>{step.agent_run?.model_runs?.map((model) => <li key={model.id}>{model.provider_model_id} · {model.status} · ModelRun {model.id}</li>)}</ul>
    </li>)}</ul></section>
    <section><h2>Éléments financiers</h2><p>Exposition estimée réservée : {row.reserved_estimated_exposure} USD. Facturation du fournisseur non vérifiée.</p>
      {evidence.length === 0 ? <p>Aucun coût modèle enregistré.</p> : <ul>{evidence.map((item) => <li key={item.model_run_id}>{item.model_run_id} : {humanize(item.classification)} ; usage estimé au catalogue {item.catalog_priced_usage ?? "inconnu"} ; réservation {item.reserved_estimated_exposure ?? "aucune"} ; coût déclaré par le fournisseur {item.provider_reported_cost ?? "inconnu"}{item.provider_report_exceeds_reservation ? " (supérieur à la réservation estimée)" : ""} ; facturation {humanize(item.provider_billing_status)}</li>)}</ul>}</section>
    <section><h2>Tentatives</h2>{history.length === 0 ? <p>Aucune tentative enregistrée.</p> : <ul>{history.map((item) => <li key={item.generation}>N° {item.generation} : {humanize(item.outcome ?? "En attente")} {item.reason_code ? ` · ${humanize(item.reason_code)}` : ""}</li>)}</ul>}</section>
    <OperatorActions dispatchId={dispatchId} status={row.status} />
  </div>;
}
