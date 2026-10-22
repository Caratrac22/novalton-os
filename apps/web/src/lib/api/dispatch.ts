import "server-only";
import { cookies } from "next/headers";
import { getApiBaseUrl, scopedApiPath, selectedOperatorScope, type WorkspaceScope } from "@/lib/api/config";
import { isUuid } from "@/lib/api/scoped";

export type DispatchSummary = {
  id: string; workflow_run_id: string; status: string; generation: number;
  task_id: string; priority: number; deadline: string; lease_expires_at: string | null;
  attempt_count: number; model_call_count: number;
  max_estimated_exposure: string | null;
  reserved_estimated_exposure: string; stop_reason: string | null;
};

export async function dispatchUpstream(path: string, init?: RequestInit, scope?: WorkspaceScope): Promise<Response | null> {
  const cookieJar = await cookies();
  const token = cookieJar.get("__Host-novalton-operator-session")?.value;
  if (!token || token.length > 8192 || !(/^[\w-]+\.[\w-]+\.[\w-]+$/.test(token) || /^nvl_[\w-]{43}$/.test(token))) return null;
  try {
    const chosen = scope ?? selectedOperatorScope(cookieJar.get("__Host-novalton-operator-workspace")?.value);
    return await fetch(`${getApiBaseUrl()}${scopedApiPath(`dispatch/${path}`, chosen)}`, {
      ...init, cache: "no-store", headers: {
        Accept: "application/json", ...(init?.headers ?? {}), Authorization: `Bearer ${token}`,
      }, signal: AbortSignal.timeout(7000),
    });
  } catch { return null; }
}

export function parseDispatches(value: unknown): DispatchSummary[] {
  if (!Array.isArray(value) || value.length > 100) throw new Error("Invalid dispatch response");
  return value.map((item: unknown) => {
    if (!item || typeof item !== "object") throw new Error("Invalid dispatch response");
    const row = item as Record<string, unknown>;
    if (!isUuid(row.id) || !isUuid(row.workflow_run_id) || !isUuid(row.task_id) ||
      typeof row.status !== "string" || typeof row.priority !== "number" ||
      typeof row.generation !== "number" || typeof row.attempt_count !== "number" ||
      typeof row.model_call_count !== "number") throw new Error("Invalid dispatch response");
    return row as DispatchSummary;
  });
}
