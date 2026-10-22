import Link from "next/link";
import { dispatchUpstream, parseDispatches } from "@/lib/api/dispatch";
import { operatorWorkspaceScopes, selectedOperatorScope } from "@/lib/api/config";
import { cookies } from "next/headers";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OperatorPage() {
  const active = selectedOperatorScope((await cookies()).get("__Host-novalton-operator-workspace")?.value);
  const candidates = operatorWorkspaceScopes();
  const [response, checks] = await Promise.all([
    dispatchUpstream("requests?limit=100"),
    Promise.all(candidates.map((scope) => dispatchUpstream("requests?limit=1", undefined, scope))),
  ]);
  const scopes = candidates.filter((_, index) => checks[index]?.ok);
  let rows;
  try { rows = response?.ok ? parseDispatches(await response.json()) : null; } catch { rows = null; }
  return <div className="page-stack operator-details">
    <section className="page-heading"><p className="eyebrow">Opérateur</p><div><h1>Exécutions durables</h1><p>Décisions autorisées pour l’espace sélectionné et état d’exécution enregistré.</p></div></section>
    <div className="operator-controls"><Link className="secondary-button" href="/api/operator/auth/start" prefetch={false}>Se connecter</Link><form action="/api/operator/auth/logout" method="post"><button type="submit">Se déconnecter</button></form>
    {scopes.length > 0 && <form action="/api/operator/workspace" method="post"><label htmlFor="operator-workspace">Espace</label><select id="operator-workspace" name="workspace_id" defaultValue={active.workspaceId}>{scopes.map((scope) =>
      <option key={scope.workspaceId} value={scope.workspaceId}>{scope.workspaceId}</option>)}</select><button type="submit">Ouvrir</button></form>}</div>
    {rows === null ? <p className="state-panel" role="status">Session expirée, permission révoquée ou service indisponible. Reconnectez-vous ou contactez l’administrateur.</p> :
      rows.length === 0 ? <p className="state-panel">Aucune demande d’exécution dans cet espace parmi les 100 premières.</p> :
        <section aria-label="Demandes d’exécution"><h2>Demandes accessibles</h2><p>100 demandes au maximum sont chargées.</p><ul className="operator-list">{rows.map((row) => <li key={row.id}>
          <Link href={`/operator/${row.id}`}>Workflow {row.workflow_run_id.slice(0, 8)} <span aria-hidden="true">→</span></Link>
          <p>Tâche {row.task_id.slice(0, 8)} · {humanize(row.status)} · priorité {row.priority} · {row.attempt_count} tentative(s) · {row.model_call_count} appel(s) modèle</p>
          {row.stop_reason && <p>Motif d’arrêt : {humanize(row.stop_reason)}</p>}
        </li>)}</ul></section>}
  </div>;
}
