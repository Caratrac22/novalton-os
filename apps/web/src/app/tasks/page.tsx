import type { Metadata } from "next";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { TaskCreateForm } from "@/components/task-create-form";
import { TaskWorkspace } from "@/components/task-workspace";
import { getProjects } from "@/lib/api/projects";
import { getProjectTasks, type TaskStatus } from "@/lib/api/tasks";
import { getOperatorWorkflow, getWorkflowRuns } from "@/lib/api/workflows";
import { formatDateTime, humanize, preview } from "@/lib/format";
import { selectVisibleRecord } from "@/lib/selection";

export const metadata: Metadata = { title: "Tâches" };
export const dynamic = "force-dynamic";
const tones = { BACKLOG: "neutral", READY: "neutral", IN_PROGRESS: "positive", BLOCKED: "negative", REVIEW: "neutral", DONE: "positive", CANCELLED: "negative" } as const satisfies Record<TaskStatus, "positive" | "negative" | "neutral">;

export default async function TasksPage({ searchParams }: Readonly<{ searchParams: Promise<{ project?: string | string[]; task?: string | string[] }> }>) {
  let projects;
  try { projects = await getProjects(); } catch { projects = null; }
  const params = await searchParams;
  const requestedId = typeof params.project === "string" ? params.project : undefined;
  const selected = selectVisibleRecord(projects ?? [], requestedId);
  let tasks = null;
  if (selected) { try { tasks = await getProjectTasks(selected.id); } catch { tasks = null; } }
  const requestedTaskId = typeof params.task === "string" ? params.task : undefined;
  const selectedTask = selectVisibleRecord(tasks ?? [], requestedTaskId);
  let workflowRuns = null;
  if (selectedTask) { try { workflowRuns = (await getWorkflowRuns()).filter((run) => run.task_id === selectedTask.id); } catch { workflowRuns = null; } }
  const initialRun = workflowRuns?.at(-1) ?? null;
  let initialWorkflow = null;
  let workflowUnavailable = false;
  if (initialRun) { try { initialWorkflow = await getOperatorWorkflow(initialRun.id); } catch { workflowUnavailable = true; } }

  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="tasks-title"><p className="eyebrow">Exécution gouvernée</p><div><h1 id="tasks-title">Tâches</h1><p>Créez un objectif, puis démarrez et suivez un workflow de développement gouverné.</p></div></section>
    {projects === null ? <StatePanel title="Tâches indisponibles">Le service des projets est indisponible ou a renvoyé des données incorrectes.</StatePanel> : projects.length === 0 ? <StatePanel title="Aucun projet">Créez un projet depuis la rubrique Projets avant d’ajouter une tâche.</StatePanel> : requestedId && !selected ? <StatePanel title="Projet inaccessible">Ce projet ne fait pas partie des projets chargés dans cet espace. Sélectionnez un projet accessible depuis la rubrique Projets.</StatePanel> : <>
      <nav className="project-selector" aria-label="Choisir un projet"><span>Projet</span><div>{projects.map((project) => <Link key={project.id} href={`/tasks?project=${project.id}`} aria-current={project.id === selected?.id ? "page" : undefined}>{project.name}</Link>)}</div></nav>
      {selected ? <><p className="section-note">{tasks?.length === 100 ? "Au moins 100 tâches : seule la première page est affichée." : tasks ? `${tasks.length} tâches chargées.` : "Chargement des tâches indisponible."}</p><TaskCreateForm projectId={selected.id} /></> : null}
      {tasks === null ? <StatePanel title="Tâches indisponibles">Les tâches de {selected?.name} n’ont pas pu être chargées.</StatePanel> : tasks.length === 0 ? <StatePanel title="Aucune tâche dans ce projet">Créez une première tâche ci-dessus. Aucun identifiant technique à copier.</StatePanel> : <>
        <section aria-label={`Tâches de ${selected?.name}`} className="record-list">{tasks.map((task) => { const description = preview(task.description); return <article className={`record-card task-card ${task.id === selectedTask?.id ? "is-selected" : ""}`} key={task.id}><div className="record-card-heading"><div><p className="record-project">{selected?.name}</p><h2>{task.title}</h2></div><StatusBadge tone={tones[task.status]}>{humanize(task.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">Aucune description.</p>}<dl className="record-meta"><div><dt>Créé le</dt><dd><time dateTime={task.createdAt}>{formatDateTime(task.createdAt)}</time></dd></div><div><dt>Mis à jour le</dt><dd><time dateTime={task.updatedAt}>{formatDateTime(task.updatedAt)}</time></dd></div></dl><Link className="card-action" href={`/tasks?project=${selected?.id}&task=${task.id}`} aria-current={task.id === selectedTask?.id ? "page" : undefined}>{task.id === selectedTask?.id ? "Tâche sélectionnée" : "Ouvrir la tâche"} <span aria-hidden="true">→</span></Link></article>; })}</section>
        {requestedTaskId && !selectedTask ? <StatePanel title="Tâche inaccessible">Cette tâche ne fait pas partie des tâches chargées pour ce projet. Choisissez une tâche de la liste.</StatePanel> : null}
        {selectedTask ? <><div className="context-line"><span>Projet / {selected?.name}</span><strong>Tâche / {selectedTask.title}</strong></div>{workflowRuns === null ? <StatePanel title="État du workflow indisponible">La tâche est visible mais l’état de son workflow n’a pas pu être chargé.</StatePanel> : workflowUnavailable ? <StatePanel title="Vue opérateur indisponible">Un workflow a été trouvé, mais son état opérateur n’a pas pu être récupéré.</StatePanel> : <TaskWorkspace projectId={selected?.id || ""} taskId={selectedTask.id} taskTitle={selectedTask.title} initialWorkflow={initialWorkflow} />}</> : null}
      </>}
    </>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
