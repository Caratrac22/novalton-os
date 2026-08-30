const UUID_PATTERN = /^[0-9a-f-]{36}$/i;

export type SafeRuntimeEvent = Readonly<{ id: string; eventType: string; source: string; occurredAt: string; projectId?: string; taskId?: string; workflowRunId?: string; summary: string; role?: string; verdict?: string; challenge?: string; reason?: string; decision?: string }>;

function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function uuid(value: unknown): value is string { return typeof value === "string" && UUID_PATTERN.test(value); }
function humanize(value: string): string { return value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function safeSummary(payload: Record<string, unknown>): string {
  for (const [key, label] of [["specialization_role", "Role"], ["qa_verdict", "QA verdict"], ["challenge_level", "Challenge"], ["reason_code", "Reason"], ["status", "Status"]]) { const value = payload[key]; if (typeof value === "string" && value.trim()) return `${label}: ${humanize(value).slice(0, 120)}`; }
  return "Operational event recorded";
}

export function parseRuntimeEventData(data: string): SafeRuntimeEvent | null {
  try {
    const value: unknown = JSON.parse(data);
    if (!record(value) || !uuid(value.id) || typeof value.event_type !== "string" || typeof value.source !== "string" || typeof value.occurred_at !== "string" || Number.isNaN(Date.parse(value.occurred_at))) return null;
    const payload = record(value.payload) ? value.payload : {};
    return { id: value.id, eventType: value.event_type, source: value.source, occurredAt: value.occurred_at, ...(uuid(value.project_id) ? { projectId: value.project_id } : {}), ...(uuid(value.task_id) ? { taskId: value.task_id } : {}), ...(uuid(payload.workflow_run_id) ? { workflowRunId: payload.workflow_run_id } : {}), ...(typeof payload.specialization_role === "string" ? { role: payload.specialization_role } : {}), ...(typeof payload.qa_verdict === "string" ? { verdict: payload.qa_verdict } : {}), ...(typeof payload.challenge_level === "string" ? { challenge: payload.challenge_level } : {}), ...(typeof payload.reason_code === "string" ? { reason: payload.reason_code } : {}), ...(typeof payload.decision === "string" ? { decision: payload.decision } : {}), summary: safeSummary(payload) };
  } catch { return null; }
}
