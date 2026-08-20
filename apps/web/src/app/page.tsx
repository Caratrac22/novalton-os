import { ModulePlaceholder } from "@/components/module-placeholder";
import { SystemStatusCard } from "@/components/system-status-card";
import { getSystemStatus } from "@/lib/api/health";

export const dynamic = "force-dynamic";

export default async function Home() {
  const status = await getSystemStatus();
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="overview-title"><p className="eyebrow">Command center</p><div><h1 id="overview-title">System overview</h1><p>Infrastructure readiness and the foundation for your operational workspace.</p></div></section>
    <SystemStatusCard status={status} />
    <section aria-labelledby="workspace-title"><div className="section-heading"><div><p className="eyebrow">Workspace</p><h2 id="workspace-title">Operational modules</h2></div><span className="section-note">Read-only preview</span></div><div className="module-grid">
      <ModulePlaceholder href="/projects" label="Projects" description="Project workspaces and progress will appear here in I-012." />
      <ModulePlaceholder href="/tasks" label="Tasks" description="Task planning and current work will appear here in I-012." />
      <ModulePlaceholder href="/activity" label="Activity" description="Scoped runtime activity will appear here in I-012." />
    </div></section>
  </div>;
}
