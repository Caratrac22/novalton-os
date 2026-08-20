import { ModulePlaceholder } from "@/components/module-placeholder";
import { SystemStatusCard } from "@/components/system-status-card";
import { getSystemStatus } from "@/lib/api/health";

export const dynamic = "force-dynamic";

export default async function Home() {
  const status = await getSystemStatus();
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="overview-title"><p className="eyebrow">Command center</p><div><h1 id="overview-title">System overview</h1><p>Infrastructure readiness and the foundation for your operational workspace.</p></div></section>
    <SystemStatusCard status={status} />
    <section aria-labelledby="workspace-title"><div className="section-heading"><div><p className="eyebrow">Workspace</p><h2 id="workspace-title">Operational modules</h2></div><span className="section-note">Live backend data</span></div><div className="module-grid">
      <ModulePlaceholder href="/projects" label="Projects" description="Browse the real projects in the configured workspace." />
      <ModulePlaceholder href="/tasks" label="Tasks" description="Select a project and inspect its bounded task list." />
      <ModulePlaceholder href="/activity" label="Activity" description="Watch the scoped RuntimeEvent stream in real time." />
    </div></section>
  </div>;
}
