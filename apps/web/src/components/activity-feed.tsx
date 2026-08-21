"use client";
import { useEffect, useState } from "react";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { formatDateTime, humanize } from "@/lib/format";

const EVENT_TYPES = ["project.created", "task.created", "workflow.run.started", "workflow.step.started", "workflow.step.completed", "workflow.step.failed", "workflow.run.waiting_for_human", "workflow.run.completed", "workflow.run.failed"] as const;
const MAX_EVENTS = 40;
type ConnectionState = "connecting" | "live" | "reconnecting" | "unavailable";
type RuntimeEvent = Readonly<{ id: string; eventType: string; source: string; occurredAt: string; projectId?: string; taskId?: string; summary: string; role?: string; verdict?: string; challenge?: string; reason?: string }>;
const stateTone: Record<ConnectionState, StatusTone> = { connecting: "neutral", live: "positive", reconnecting: "neutral", unavailable: "negative" };

function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function uuid(value: unknown): value is string { return typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value); }
function safeSummary(payload: unknown): string {
  if (!record(payload)) return "Operational event recorded";
  for (const [key, label] of [["specialization_role", "Role"], ["qa_verdict", "QA verdict"], ["challenge_level", "Challenge"], ["reason_code", "Reason"], ["status", "Status"]]) { const value = payload[key]; if (typeof value === "string" && value.trim()) return `${label}: ${humanize(value).slice(0, 120)}`; }
  return "Operational event recorded";
}
function parseEvent(message: MessageEvent<string>): RuntimeEvent | null {
  try {
    const value: unknown = JSON.parse(message.data);
    if (!record(value) || !uuid(value.id) || typeof value.event_type !== "string" || typeof value.source !== "string" || typeof value.occurred_at !== "string" || Number.isNaN(Date.parse(value.occurred_at))) return null;
    const payload = record(value.payload) ? value.payload : {};
    return { id: value.id, eventType: value.event_type, source: value.source, occurredAt: value.occurred_at, ...(uuid(value.project_id) ? { projectId: value.project_id } : {}), ...(uuid(value.task_id) ? { taskId: value.task_id } : {}), ...(typeof payload.specialization_role === "string" ? { role: payload.specialization_role } : {}), ...(typeof payload.qa_verdict === "string" ? { verdict: payload.qa_verdict } : {}), ...(typeof payload.challenge_level === "string" ? { challenge: payload.challenge_level } : {}), ...(typeof payload.reason_code === "string" ? { reason: payload.reason_code } : {}), summary: safeSummary(value.payload) };
  } catch { return null; }
}

export function ActivityFeed() {
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  useEffect(() => {
    const source = new EventSource("/api/activity/stream");
    let failures = 0;
    const receive = (message: MessageEvent<string>) => { const event = parseEvent(message); if (!event) return; setEvents((current) => [event, ...current.filter((item) => item.id !== event.id)].slice(0, MAX_EVENTS)); };
    source.onopen = () => { failures = 0; setConnection("live"); };
    source.onerror = () => { failures += 1; setConnection(failures >= 5 ? "unavailable" : "reconnecting"); };
    for (const type of EVENT_TYPES) source.addEventListener(type, receive as EventListener);
    return () => source.close();
  }, []);
  return <section className="activity-panel" aria-labelledby="activity-feed-title"><div className="activity-header"><div><h2 id="activity-feed-title">Runtime events</h2><p>Newest first · up to {MAX_EVENTS} events retained in memory</p></div><StatusBadge tone={stateTone[connection]}>{humanize(connection)}</StatusBadge></div><div className="sr-status" role="status" aria-live="polite">Activity connection is {connection}.</div>{events.length === 0 ? <div className="activity-empty"><h3>{connection === "live" ? "Waiting for activity" : "Connecting to activity"}</h3><p>Project, task, and governed workflow events will appear here without being stored in the browser.</p></div> : <ol className="activity-list">{events.map((event) => <li key={event.id}><div className="activity-marker" aria-hidden="true" /><article><div className="activity-event-heading"><h3>{humanize(event.eventType.replaceAll(".", " "))}</h3><time dateTime={event.occurredAt}>{formatDateTime(event.occurredAt)}</time></div><p>{event.summary}</p><dl className="activity-meta"><div><dt>Source</dt><dd>{event.source}</dd></div>{event.role ? <div><dt>Role</dt><dd>{humanize(event.role)}</dd></div> : null}{event.verdict ? <div><dt>QA</dt><dd>{humanize(event.verdict)}</dd></div> : null}{event.challenge ? <div><dt>Challenge</dt><dd>{humanize(event.challenge)}</dd></div> : null}{event.reason ? <div><dt>Reason</dt><dd>{humanize(event.reason)}</dd></div> : null}{event.projectId ? <div><dt>Project</dt><dd title={event.projectId}>{event.projectId.slice(0, 8)}</dd></div> : null}{event.taskId ? <div><dt>Task</dt><dd title={event.taskId}>{event.taskId.slice(0, 8)}</dd></div> : null}</dl></article></li>)}</ol>}</section>;
}
