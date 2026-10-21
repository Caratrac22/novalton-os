import Link from "next/link";
import { dispatchUpstream, parseDispatches } from "@/lib/api/dispatch";
import { operatorWorkspaceScopes, selectedOperatorScope } from "@/lib/api/config";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

export default async function OperatorPage() {
  const active = selectedOperatorScope((await cookies()).get("__Host-novalton-operator-workspace")?.value);
  const scopes = operatorWorkspaceScopes();
  const response = await dispatchUpstream("requests?limit=100");
  let rows;
  try { rows = response?.ok ? parseDispatches(await response.json()) : null; } catch { rows = null; }
  return <main className="page-stack">
    <section className="page-heading"><p className="eyebrow">Operator</p><div><h1>Durable workflows</h1><p>Verified workspace decisions and persisted execution state.</p></div></section>
    <p><Link href="/api/operator/auth/start" prefetch={false}>Sign in</Link> · <form action="/api/operator/auth/logout" method="post" style={{ display: "inline" }}><button type="submit">Sign out</button></form></p>
    <form action="/api/operator/workspace" method="post"><label>Workspace <select name="workspace_id" defaultValue={active.workspaceId}>{scopes.map((scope) =>
      <option key={scope.workspaceId} value={scope.workspaceId}>{scope.workspaceId}</option>)}</select></label><button type="submit">Open workspace</button></form>
    {rows === null ? <p role="status">Operator session expired, workspace permission revoked, or service unavailable. Sign in again or contact an operator administrator.</p> :
      rows.length === 0 ? <p>No dispatch requests in this workspace.</p> :
        <section aria-label="Dispatch requests"><ul>{rows.map((row) => <li key={row.id}>
          <Link href={`/operator/${row.id}`}>Workflow {row.workflow_run_id}</Link>
          <span> · Task {row.task_id} · {row.status} · priority {row.priority} · {row.attempt_count} attempts · {row.model_call_count} model calls</span>
          {row.stop_reason && <span> · {row.stop_reason}</span>}
        </li>)}</ul></section>}
  </main>;
}
