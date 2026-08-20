import type { Metadata } from "next";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { getProjects } from "@/lib/api/projects";
import { getProjectTasks, type TaskStatus } from "@/lib/api/tasks";
import { formatDateTime, humanize, preview } from "@/lib/format";

export const metadata: Metadata = { title: "Tasks" };
export const dynamic = "force-dynamic";
const tones = { BACKLOG: "neutral", READY: "neutral", IN_PROGRESS: "positive", BLOCKED: "negative", REVIEW: "neutral", DONE: "positive", CANCELLED: "negative" } as const satisfies Record<TaskStatus, "positive" | "negative" | "neutral">;

export default async function TasksPage({ searchParams }: Readonly<{ searchParams: Promise<{ project?: string | string[] }> }>) {
  let projects;
  try { projects = await getProjects(); } catch { projects = null; }
  const requested = (await searchParams).project;
  const requestedId = typeof requested === "string" ? requested : undefined;
  const selected = projects?.find((project) => project.id === requestedId) ?? projects?.[0];
  let tasks = null;
  if (selected) { try { tasks = await getProjectTasks(selected.id); } catch { tasks = null; } }
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="tasks-title"><p className="eyebrow">Execution</p><div><h1 id="tasks-title">Tasks</h1><p>Read-only user task state, loaded for one explicitly selected project.</p></div></section>
    {projects === null ? <StatePanel title="Tasks unavailable">The project service could not be reached or returned an invalid response.</StatePanel> : projects.length === 0 ? <StatePanel title="No projects yet">Create a project through the API before viewing project-scoped tasks.</StatePanel> : <><nav className="project-selector" aria-label="Select project"><span>Project</span><div>{projects.map((project) => <Link key={project.id} href={`/tasks?project=${project.id}`} aria-current={project.id === selected?.id ? "page" : undefined}>{project.name}</Link>)}</div></nav>{tasks === null ? <StatePanel title="Tasks unavailable">Tasks for {selected?.name} could not be reached or returned an invalid response.</StatePanel> : tasks.length === 0 ? <StatePanel title="No tasks in this project">{selected?.name} has no tasks to display.</StatePanel> : <section aria-label={`Tasks for ${selected?.name}`} className="record-list">{tasks.map((task) => { const description = preview(task.description); return <article className="record-card task-card" key={task.id}><div className="record-card-heading"><div><p className="record-project">{selected?.name}</p><h2>{task.title}</h2></div><StatusBadge tone={tones[task.status]}>{humanize(task.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">No description provided.</p>}<dl className="record-meta"><div><dt>Created</dt><dd><time dateTime={task.createdAt}>{formatDateTime(task.createdAt)}</time></dd></div><div><dt>Updated</dt><dd><time dateTime={task.updatedAt}>{formatDateTime(task.updatedAt)}</time></dd></div></dl></article>; })}</section>}</>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
