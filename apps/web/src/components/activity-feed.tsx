"use client";
import { useEffect, useState } from "react";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { formatDateTime, humanize } from "@/lib/format";
import { parseRuntimeEventData, type SafeRuntimeEvent } from "@/lib/runtime-event";

const EVENT_TYPES = ["project.created", "task.created", "workflow.run.started", "workflow.step.started", "workflow.step.completed", "workflow.step.failed", "workflow.run.waiting_for_human", "workflow.challenge.resolved", "workflow.run.completed", "workflow.run.failed"] as const;
const MAX_EVENTS = 40;
type ConnectionState = "connecting" | "live" | "reconnecting" | "unavailable";
type ActivityFeedProps = Readonly<{ projectId?: string; taskId?: string; workflowRunId?: string; onWorkflowEvent?: () => void }>;
const stateTone: Record<ConnectionState, StatusTone> = { connecting: "neutral", live: "positive", reconnecting: "neutral", unavailable: "negative" };

export function ActivityFeed({ projectId, taskId, workflowRunId, onWorkflowEvent }: ActivityFeedProps = {}) {
  const [events, setEvents] = useState<SafeRuntimeEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  useEffect(() => {
    const source = new EventSource("/api/activity/stream");
    let failures = 0;
    const receive = (message: MessageEvent<string>) => { const event = parseRuntimeEventData(message.data); if (!event || (projectId && event.projectId !== projectId) || (taskId && event.taskId !== taskId) || (workflowRunId && event.workflowRunId !== workflowRunId)) return; setEvents((current) => [event, ...current.filter((item) => item.id !== event.id)].slice(0, MAX_EVENTS)); onWorkflowEvent?.(); };
    source.onopen = () => { failures = 0; setConnection("live"); };
    source.onerror = () => { failures += 1; setConnection(failures >= 5 ? "unavailable" : "reconnecting"); };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive as EventListener);
    return () => source.close();
  }, [onWorkflowEvent, projectId, taskId, workflowRunId]);
  return <section className="activity-panel" aria-labelledby="activity-feed-title"><div className="activity-header"><div><h2 id="activity-feed-title">{workflowRunId ? "Workflow activity" : "Runtime events"}</h2><p>Newest first · up to {MAX_EVENTS} safe events retained in memory</p></div><StatusBadge tone={stateTone[connection]}>{humanize(connection)}</StatusBadge></div><div className="sr-status" role="status" aria-live="polite">Activity connection is {connection}.</div>{events.length === 0 ? <div className="activity-empty"><h3>{connection === "live" ? "Waiting for activity" : "Connecting to activity"}</h3><p>Governed lifecycle events will appear here without prompts, handoffs, provider payloads, or Memory content.</p></div> : <ol className="activity-list">{events.map((event) => <li key={event.id}><div className="activity-marker" aria-hidden="true" /><article><div className="activity-event-heading"><h3>{humanize(event.eventType.replaceAll(".", " "))}</h3><time dateTime={event.occurredAt}>{formatDateTime(event.occurredAt)}</time></div><p>{event.summary}</p><dl className="activity-meta"><div><dt>Source</dt><dd>{event.source}</dd></div>{event.role ? <div><dt>Role</dt><dd>{humanize(event.role)}</dd></div> : null}{event.verdict ? <div><dt>QA</dt><dd>{humanize(event.verdict)}</dd></div> : null}{event.challenge ? <div><dt>Challenge</dt><dd>{humanize(event.challenge)}</dd></div> : null}{event.decision ? <div><dt>Decision</dt><dd>{humanize(event.decision)}</dd></div> : null}{event.reason ? <div><dt>Reason</dt><dd>{humanize(event.reason)}</dd></div> : null}{event.projectId ? <div><dt>Project</dt><dd title={event.projectId}>{event.projectId.slice(0, 8)}</dd></div> : null}{event.taskId ? <div><dt>Task</dt><dd title={event.taskId}>{event.taskId.slice(0, 8)}</dd></div> : null}</dl></article></li>)}</ol>}</section>;
}
