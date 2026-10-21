import { dispatchUpstream } from "@/lib/api/dispatch";
import { isUuid } from "@/lib/api/scoped";
import { OperatorActions } from "./operator-actions";

export const dynamic = "force-dynamic";

type Detail = { workflow_plan?: { title?: string }; workflow_run?: { status?: string }; step_details?: Array<{ specialization_role?: string | null; agent_run?: { status?: string; model_runs?: Array<{ id?: string; status?: string; provider_model_id?: string }> } | null; challenge?: { challenge_level?: string; decision?: string | null } | null }> };
type Cost = { model_run_id: string; classification: string; catalog_priced_usage: string | null; reserved_estimated_exposure: string | null; provider_billing_status: string };
type Attempt = { generation: number; outcome: string | null; reason_code: string | null };

export default async function OperatorDetail({ params }: { params: Promise<{ dispatchId: string }> }) {
  const { dispatchId } = await params;
  if (!isUuid(dispatchId)) return <p>Invalid dispatch identifier.</p>;
  const [requests, workflow, costs, attempts] = await Promise.all([
    dispatchUpstream("requests?limit=100"),
    dispatchUpstream(`requests/${dispatchId}/workflow`),
    dispatchUpstream(`requests/${dispatchId}/cost-evidence`),
    dispatchUpstream(`requests/${dispatchId}/attempts`),
  ]);
  if (!requests?.ok || !workflow?.ok || !costs?.ok || !attempts?.ok) return <p role="status">Operator evidence unavailable or access revoked.</p>;
  const list = await requests.json() as Array<{ id: string; status: string; stop_reason: string | null; workflow_run_id: string; reserved_estimated_exposure: string }>;
  const row = list.find((item) => item.id === dispatchId);
  if (!row) return <p>Dispatch outside the current operator view.</p>;
  const details = await workflow.json() as Detail;
  const evidence = await costs.json() as Cost[];
  const history = await attempts.json() as Attempt[];
  return <main className="page-stack">
    <section className="page-heading"><p className="eyebrow">Operator · {row.status}</p><div><h1>{details.workflow_plan?.title ?? "Workflow"}</h1><p>{row.workflow_run_id} · {details.workflow_run?.status ?? "Unknown"}</p></div></section>
    {row.stop_reason && <p role="status">Blocked: {row.stop_reason}</p>}
    <section><h2>Manager → Developer → QA</h2><ul>{details.step_details?.map((step, index) => <li key={index}>
      {step.specialization_role ?? "Step"} · {step.agent_run?.status ?? "Pending"}
      {step.challenge && <strong> · Human review {step.challenge.decision ?? "pending"} ({step.challenge.challenge_level})</strong>}
      <ul>{step.agent_run?.model_runs?.map((model) => <li key={model.id}>{model.provider_model_id} · {model.status} · ModelRun {model.id}</li>)}</ul>
    </li>)}</ul></section>
    <section><h2>Financial evidence</h2><p>Reserved catalog exposure: {row.reserved_estimated_exposure} USD. Provider billing is unverified.</p>
      <ul>{evidence.map((item) => <li key={item.model_run_id}>{item.model_run_id}: {item.classification}; catalog-priced usage {item.catalog_priced_usage ?? "unknown"}; reserved {item.reserved_estimated_exposure ?? "none"}; billing {item.provider_billing_status}</li>)}</ul></section>
    <section><h2>Attempts</h2><ul>{history.map((item) => <li key={item.generation}>#{item.generation}: {item.outcome ?? "pending"} {item.reason_code ?? ""}</li>)}</ul></section>
    <OperatorActions dispatchId={dispatchId} status={row.status} />
  </main>;
}
