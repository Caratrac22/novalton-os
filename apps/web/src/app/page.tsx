import Link from "next/link";
import { ModulePlaceholder } from "@/components/module-placeholder";
import { SystemStatusCard } from "@/components/system-status-card";
import { getSystemStatus } from "@/lib/api/health";
import { getProjects } from "@/lib/api/projects";
import { scopedErrorMessage } from "@/lib/api/scoped";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [status, projectResult] = await Promise.all([
    getSystemStatus(),
    getProjects().then((projects) => ({ projects, error: null })).catch((error: unknown) => ({ projects: null, error })),
  ]);
  return <div className="page-stack">
    <section className="hero-panel" aria-labelledby="home-title">
      <p className="eyebrow">Votre espace de travail</p>
      <h1 id="home-title">Transformez un objectif en projet concret.</h1>
      <p>Organisez vos projets, créez des tâches et suivez leur exécution gouvernée. Le dialogue de cadrage conserve désormais vos échanges par projet. Une réponse IA est disponible lorsque vous configurez un modèle local ; les agents restent soumis à leur lancement gouverné.</p>
      <div className="hero-actions"><Link className="primary-button" href="/projects">Créer ou ouvrir un projet <span aria-hidden="true">→</span></Link><Link className="secondary-button" href="/control">Centre de contrôle</Link></div>
    </section>
    <section aria-labelledby="workspace-summary-title"><div className="section-heading"><div><p className="eyebrow">Vue d’ensemble</p><h2 id="workspace-summary-title">Projets dans cet espace</h2></div><span className="section-note">Première page, 100 projets au maximum</span></div>
      {projectResult.projects === null ? <div className="state-panel" role="status"><h2>Projets indisponibles</h2><p>{scopedErrorMessage(projectResult.error)} <Link href="/login">Se connecter</Link>.</p></div> :
        <div className="summary-panel"><div><strong className="summary-number">{projectResult.projects.length === 100 ? "≥ 100" : projectResult.projects.length}</strong><span>projet{projectResult.projects.length > 1 ? "s" : ""} chargé{projectResult.projects.length > 1 ? "s" : ""}</span></div>
          <div><h3>{projectResult.projects.length === 0 ? "Aucun projet pour le moment" : "Reprendre le travail"}</h3><p>{projectResult.projects.length === 0 ? "Créez un projet avant de lancer une mission." : "Retrouvez les tâches et les workflows de vos projets existants."}</p><Link href={projectResult.projects[0] ? `/tasks?project=${projectResult.projects[0].id}` : "/projects"}>Continuer <span aria-hidden="true">→</span></Link></div>
        </div>}
      {projectResult.projects?.length ? <div className="recent-projects"><h3>Accès rapide aux projets</h3><ul>{projectResult.projects.slice(0, 5).map((project) => <li key={project.id}><Link href={`/tasks?project=${project.id}`}>{project.name} <span aria-hidden="true">→</span></Link></li>)}</ul></div> : null}
    </section>
    <SystemStatusCard status={status} />
    <section aria-labelledby="modules-title"><div className="section-heading"><div><p className="eyebrow">Espaces</p><h2 id="modules-title">Accéder aux fonctionnalités</h2></div></div><div className="module-grid">
      <ModulePlaceholder href="/projects" label="Projets" description="Créer et consulter des projets dans l’espace configuré." />
      <ModulePlaceholder href="/tasks" label="Tâches" description="Définir un objectif et superviser son workflow gouverné." />
      <ModulePlaceholder href="/control" label="Centre de contrôle" description="Consulter l’activité en direct et les décisions opérateur." />
    </div></section>
  </div>;
}
