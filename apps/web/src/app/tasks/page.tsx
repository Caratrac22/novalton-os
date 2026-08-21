import type { Metadata } from "next";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { getProjects } from "@/lib/api/projects";
import { getProjectTasks, type TaskStatus } from "@/lib/api/tasks";
import { getWorkflowPlan, getWorkflowRuns } from "@/lib/api/workflows";
import { TaskWorkspace } from "@/components/task-workspace";
import { formatDateTime, humanize, preview } from "@/lib/format";

export const metadata: Metadata = { title: "Tasks" };
export const dynamic = "force-dynamic";
const tones = { BACKLOG: "neutral", READY: "neutral", IN_PROGRESS: "positive", BLOCKED: "negative", REVIEW: "neutral", DONE: "positive", CANCELLED: "negative" } as const satisfies Record<TaskStatus, "positive" | "negative" | "neutral">;

export default async function TasksPage({ searchParams }: Readonly<{ searchParams: Promise<{ project?: string | string[]; task?: string | string[] }> }>) {
  let projects;
  try { projects = await getProjects(); } catch { projects = null; }
  const params = await searchParams;
  const requested = params.project;
  const requestedId = typeof requested === "string" ? requested : undefined;
  const selected = projects?.find((project) => project.id === requestedId) ?? projects?.[0];
  const requestedTask = params.task;
  const requestedTaskId = typeof requestedTask === "string" ? requestedTask : undefined;
  let tasks = null;
  if (selected) { try { tasks = await getProjectTasks(selected.id); } catch { tasks = null; } }
  const selectedTask = tasks?.find((task) => task.id === requestedTaskId) ?? tasks?.[0];
  let workflowRuns = null;
  if (selectedTask) { try { workflowRuns = (await getWorkflowRuns()).filter((run) => run.task_id === selectedTask.id); } catch { workflowRuns = null; } }
  const initialRun = workflowRuns?.[0] ?? null;
  let initialPlan = null;
  let planUnavailable = false;
  if (initialRun) { try { initialPlan = await getWorkflowPlan(initialRun.workflow_plan_id); } catch { planUnavailable = true; } }
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="tasks-title"><p className="eyebrow">Execution</p><div><h1 id="tasks-title">Tasks</h1><p>Read-only user task state, loaded for one explicitly selected project.</p></div></section>
    {projects === null ? <StatePanel title="Tasks unavailable">The project service could not be reached or returned an invalid response.</StatePanel> : projects.length === 0 ? <StatePanel title="No projects yet">Create a project through the API before viewing project-scoped tasks.</StatePanel> : <><nav className="project-selector" aria-label="Select project"><span>Project</span><div>{projects.map((project) => <Link key={project.id} href={`/tasks?project=${project.id}`} aria-current={project.id === selected?.id ? "page" : undefined}>{project.name}</Link>)}</div></nav>{tasks === null ? <StatePanel title="Tasks unavailable">Tasks for {selected?.name} could not be reached or returned an invalid response.</StatePanel> : tasks.length === 0 ? <StatePanel title="No tasks in this project">{selected?.name} has no tasks to display.</StatePanel> : <><section aria-label={`Tasks for ${selected?.name}`} className="record-list">{tasks.map((task) => { const description = preview(task.description); return <article className={`record-card task-card ${task.id === selectedTask?.id ? "is-selected" : ""}`} key={task.id}><div className="record-card-heading"><div><p className="record-project">{selected?.name}</p><h2>{task.title}</h2></div><StatusBadge tone={tones[task.status]}>{humanize(task.status)}</StatusBadge></div>{description ? <p className="record-description">{description}</p> : <p className="record-description record-description-empty">No description provided.</p>}<dl className="record-meta"><div><dt>Created</dt><dd><time dateTime={task.createdAt}>{formatDateTime(task.createdAt)}</time></dd></div><div><dt>Updated</dt><dd><time dateTime={task.updatedAt}>{formatDateTime(task.updatedAt)}</time></dd></div></dl><Link className="card-action" href={`/tasks?project=${selected?.id}&task=${task.id}`} aria-current={task.id === selectedTask?.id ? "page" : undefined}>{task.id === selectedTask?.id ? "Selected task" : "Open task"} <span aria-hidden="true">→</span></Link></article>; })}</section>{selectedTask ? <><div className="context-line"><span>Project / {selected?.name}</span><strong>Task / {selectedTask.title}</strong></div>{workflowRuns === null ? <StatePanel title="Workflow state unavailable">The task is visible, but its workflow state could not be loaded.</StatePanel> : planUnavailable ? <StatePanel title="Workflow plan unavailable">An existing workflow run was found, but its plan could not be read. No new workflow will be created from this view.</StatePanel> : <TaskWorkspace projectId={selected?.id || ""} taskId={selectedTask.id} taskTitle={selectedTask.title} initialRun={initialRun} initialPlan={initialPlan} />}</> : null}</>}</>}
  </div>;
}

function StatePanel({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) { return <section className="state-panel" role="status"><h2>{title}</h2><p>{children}</p></section>; }
