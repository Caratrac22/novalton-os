import type { Metadata } from "next";
import { StatusBadge } from "@/components/status-badge";
import Link from "next/link";
import { formatDateTime, humanize, preview } from "@/lib/format";
import { getProjects, type ProjectStatus } from "@/lib/api/projects";
import { ProjectCreateForm } from "@/components/project-create-form";
import { PAGE_SIZE, pageHref, pageOffset } from "@/lib/pagination";
import { scopedErrorMessage } from "@/lib/api/scoped";

export const metadata: Metadata = { title: "Projets" };
export const dynamic = "force-dynamic";
const tones = { ACTIVE: "positive", PAUSED: "neutral", ARCHIVED: "neutral" } as const satisfies Record<ProjectStatus, "positive" | "neutral">;

export default async function ProjectsPage({ searchParams }: Readonly<{ searchParams: Promise<{ page?: string | string[] }> }>) {
  const offset = pageOffset((await searchParams).page);
  let projects;
  let problem: unknown = null;
  try { projects = offset === null ? null : await getProjects(offset, PAGE_SIZE); } catch (error) { projects = null; problem = error; }
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="projects-title"><p className="eyebrow">Espace de travail</p><div><h1 id="projects-title">Projets</h1><p>Choisissez un projet existant ou créez-en un dans l’espace configuré.</p></div></section>
    <ProjectCreateForm />
    {offset === null ? <StatePanel title="Page invalide">Choisissez une page valide.</StatePanel> : projects === null ? <StatePanel title="Projets indisponibles">{scopedErrorMessage(problem)} <Link href="/api/operator/auth/start">Se connecter</Link>.</StatePanel> : projects.length === 0 && offset === 0 ? <StatePanel title="Aucun projet">Créez votre premier projet ci-dessus pour préparer une mission.</StatePanel> : <><p className="section-note">Page {offset / PAGE_SIZE + 1} · {projects.length} projets chargés.</p><section aria-label="Projets" className="record-grid">{projects.map((project) => { const description = preview(project.description); return <article className="record-card" key={project.id}><div className="record-card-heading"><div><h2>{project.name}</h2><span className="record-slug">{project.slug}</span></div><StatusBadge tone={tones[project.status]}>{humanize(project.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">Aucune description.</p>}<dl className="record-meta"><div><dt>Créé le</dt><dd><time dateTime={project.createdAt}>{formatDateTime(project.createdAt)}</time></dd></div><div><dt>Mis à jour le</dt><dd><time dateTime={project.updatedAt}>{formatDateTime(project.updatedAt)}</time></dd></div></dl><Link className="card-action" href={`/tasks?project=${project.id}`}>Ouvrir les tâches du projet <span aria-hidden="true">→</span></Link><Link className="card-action" href={`/projects/${project.id}/chat`}>Discuter de cet objectif <span aria-hidden="true">→</span></Link></article>; })}</section><nav className="pagination" aria-label="Pages de projets">{offset > 0 && <Link href={pageHref("/projects", {}, offset - PAGE_SIZE)}>← Précédent</Link>}{projects.length === PAGE_SIZE && <Link href={pageHref("/projects", {}, offset + PAGE_SIZE)}>Suivant →</Link>}</nav></>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
