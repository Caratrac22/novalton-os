import type { Metadata } from "next";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime, humanize, preview } from "@/lib/format";
import { getProjects, type ProjectStatus } from "@/lib/api/projects";

export const metadata: Metadata = { title: "Projects" };
export const dynamic = "force-dynamic";
const tones = { ACTIVE: "positive", PAUSED: "neutral", ARCHIVED: "neutral" } as const satisfies Record<ProjectStatus, "positive" | "neutral">;

export default async function ProjectsPage() {
  let projects;
  try { projects = await getProjects(); } catch { projects = null; }
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="projects-title"><p className="eyebrow">Workspace</p><div><h1 id="projects-title">Projects</h1><p>Read-only project workspaces from the configured tenant and workspace.</p></div></section>
    {projects === null ? <StatePanel title="Projects unavailable">The project service could not be reached or returned an invalid response. Try again when the API is available.</StatePanel> : projects.length === 0 ? <StatePanel title="No projects yet">This workspace has no projects to display.</StatePanel> : <section aria-label="Projects" className="record-grid">{projects.map((project) => { const description = preview(project.description); return <article className="record-card" key={project.id}><div className="record-card-heading"><div><h2>{project.name}</h2><span className="record-slug">{project.slug}</span></div><StatusBadge tone={tones[project.status]}>{humanize(project.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">No description provided.</p>}<dl className="record-meta"><div><dt>Created</dt><dd><time dateTime={project.createdAt}>{formatDateTime(project.createdAt)}</time></dd></div><div><dt>Updated</dt><dd><time dateTime={project.updatedAt}>{formatDateTime(project.updatedAt)}</time></dd></div></dl></article>; })}</section>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
