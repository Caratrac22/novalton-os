import type { Metadata } from "next";
import Link from "next/link";
import { ActivityFeed } from "@/components/activity-feed";
import { getWorkflowRuns } from "@/lib/api/workflows";
import { summarizeWorkflows } from "@/lib/workflow-summary";
import { humanize } from "@/lib/format";
import { PAGE_SIZE, pageHref, pageOffset } from "@/lib/pagination";

export const metadata: Metadata = { title: "Centre de contrôle" };
export const dynamic = "force-dynamic";

export default async function ControlPage({ searchParams }: Readonly<{ searchParams: Promise<{ page?: string | string[] }> }>) {
  const offset = pageOffset((await searchParams).page);
  const runs = offset === null ? null : await getWorkflowRuns(offset, PAGE_SIZE).catch(() => null);
  const summary = runs === null ? null : summarizeWorkflows(runs);
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="control-title"><p className="eyebrow">Supervision</p><div><h1 id="control-title">Centre de contrôle</h1><p>Consultez les workflows accessibles, les événements d’exécution et les décisions opérateur, sans contourner les approbations requises.</p></div></section>
    <section aria-labelledby="control-state-title"><div className="section-heading"><div><p className="eyebrow">Suivi du travail</p><h2 id="control-state-title">État des workflows</h2></div><span className="section-note">{offset === null ? "Page invalide" : `Page ${offset / PAGE_SIZE + 1} · jusqu’à ${PAGE_SIZE} exécutions`}</span></div>
      {summary === null ? <div className="state-panel" role="status"><h2>État indisponible</h2><p>Impossible de consulter les workflows. Cette erreur n’est pas assimilée à zéro exécution.</p></div> :
      <div className="metric-grid" aria-label="Workflows chargés par statut">
        <div className="metric-card"><strong>{summary.RUNNING}</strong><span>En cours</span></div>
        <div className="metric-card"><strong>{summary.CREATED}</strong><span>Créés</span></div>
        <div className="metric-card"><strong>{summary.COMPLETED}</strong><span>Terminés</span></div>
        <div className="metric-card"><strong>{summary.FAILED + summary.CANCELLED}</strong><span>Échecs et annulations</span></div>
      </div>}
      {runs?.length ? <div className="recent-projects"><h3>Exécutions accessibles sur cette page</h3><ul>{runs.map((run) => <li key={run.id}><span>{run.id.slice(0, 8)} · {humanize(run.status)} · tâche {run.task_id.slice(0, 8)}</span></li>)}</ul><p>Pour consulter les étapes et agir, ouvrez la tâche correspondante depuis Projets ou la console opérateur authentifiée.</p></div> : null}
      {runs && offset !== null ? <nav className="pagination" aria-label="Pages des workflows">{offset > 0 && <Link href={pageHref("/control", {}, offset - PAGE_SIZE)}>← Précédent</Link>}{runs.length === PAGE_SIZE && <Link href={pageHref("/control", {}, offset + PAGE_SIZE)}>Suivant →</Link>}</nav> : null}
    </section>
    <section className="module-grid" aria-label="Actions de supervision">
      <Link className="module-card" href="/operator"><div><h3>Console opérateur</h3><p>Afficher les demandes durables, leur état et les actions autorisées pour la session authentifiée.</p></div><span className="module-link">Ouvrir la console <span aria-hidden="true">→</span></span></Link>
      <Link className="module-card" href="/tasks"><div><h3>Missions et workflows</h3><p>Sélectionner une tâche, consulter les étapes Manager, Developer et QA ainsi que leurs résultats.</p></div><span className="module-link">Voir les missions <span aria-hidden="true">→</span></span></Link>
      <Link className="module-card" href="/activity"><div><h3>Journal d’activité</h3><p>Consulter le flux de RuntimeEvents. Le flux ne remplace pas un historique complet après reconnexion.</p></div><span className="module-link">Ouvrir le journal <span aria-hidden="true">→</span></span></Link>
    </section>
    <ActivityFeed />
  </div>;
}
