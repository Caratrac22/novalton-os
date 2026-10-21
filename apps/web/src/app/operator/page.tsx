import Link from "next/link";
import { dispatchUpstream, parseDispatches } from "@/lib/api/dispatch";

export const dynamic = "force-dynamic";

export default async function OperatorPage() {
  const response = await dispatchUpstream("requests?limit=100");
  let rows;
  try { rows = response?.ok ? parseDispatches(await response.json()) : null; } catch { rows = null; }
  return <main className="page-stack">
    <section className="page-heading"><p className="eyebrow">Operator</p><div><h1>Durable workflows</h1><p>Verified workspace decisions and persisted execution state.</p></div></section>
    {rows === null ? <p role="status">Operator session or workspace permission unavailable. Sign in through the configured identity gateway.</p> :
      rows.length === 0 ? <p>No dispatch requests in this workspace.</p> :
        <section aria-label="Dispatch requests"><ul>{rows.map((row) => <li key={row.id}>
          <Link href={`/operator/${row.id}`}>Workflow {row.workflow_run_id}</Link>
          <span> · Task {row.task_id} · {row.status} · priority {row.priority} · {row.attempt_count} attempts · {row.model_call_count} model calls</span>
          {row.stop_reason && <span> · {row.stop_reason}</span>}
        </li>)}</ul></section>}
  </main>;
}
