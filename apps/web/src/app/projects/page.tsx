import type { Metadata } from "next";
import { StatusBadge } from "@/components/status-badge";
import Link from "next/link";
import { formatDateTime, humanize, preview } from "@/lib/format";
import { getProjects, type ProjectStatus } from "@/lib/api/projects";
import { ProjectCreateForm } from "@/components/project-create-form";

export const metadata: Metadata = { title: "Projets" };
export const dynamic = "force-dynamic";
const tones = { ACTIVE: "positive", PAUSED: "neutral", ARCHIVED: "neutral" } as const satisfies Record<ProjectStatus, "positive" | "neutral">;

export default async function ProjectsPage() {
  let projects;
  try { projects = await getProjects(); } catch { projects = null; }
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="projects-title"><p className="eyebrow">Espace de travail</p><div><h1 id="projects-title">Projets</h1><p>Choisissez un projet existant ou créez-en un dans l’espace configuré.</p></div></section>
    <ProjectCreateForm />
    {projects === null ? <StatePanel title="Projets indisponibles">Le service des projets ne répond pas ou a renvoyé des données incorrectes. Réessayez lorsque l’API sera disponible.</StatePanel> : projects.length === 0 ? <StatePanel title="Aucun projet">Créez votre premier projet ci-dessus pour préparer une mission.</StatePanel> : <section aria-label="Projets" className="record-grid">{projects.map((project) => { const description = preview(project.description); return <article className="record-card" key={project.id}><div className="record-card-heading"><div><h2>{project.name}</h2><span className="record-slug">{project.slug}</span></div><StatusBadge tone={tones[project.status]}>{humanize(project.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">Aucune description.</p>}<dl className="record-meta"><div><dt>Créé le</dt><dd><time dateTime={project.createdAt}>{formatDateTime(project.createdAt)}</time></dd></div><div><dt>Mis à jour le</dt><dd><time dateTime={project.updatedAt}>{formatDateTime(project.updatedAt)}</time></dd></div></dl><Link className="card-action" href={`/tasks?project=${project.id}`}>Ouvrir les tâches du projet <span aria-hidden="true">→</span></Link></article>; })}</section>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
