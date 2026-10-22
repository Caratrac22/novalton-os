import "server-only";
import { cookies } from "next/headers";
import { getApiBaseUrl, scopedApiPath, operatorWorkspaceScopes } from "@/lib/api/config";

export class ApiUnavailableError extends Error {
  constructor() { super("Workspace data is unavailable"); }
}

/** A request-scoped cookie is only a token carrier; FastAPI verifies it and the selected scope. */
export async function scopedSessionFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const jar = await cookies();
  const token = jar.get("__Host-novalton-operator-session")?.value;
  if (!token || token.length > 8192 || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(token))
    return Response.json({ message: "Connexion requise." }, { status: 401 });
  const selected = jar.get("__Host-novalton-operator-workspace")?.value;
  const scopes = operatorWorkspaceScopes();
  const scope = selected ? scopes.find((entry) => entry.workspaceId === selected) : scopes[0];
  if (!scope) return Response.json({ message: "Espace non autorisé." }, { status: 403 });
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", headers.get("Accept") ?? "application/json");
  return fetch(`${getApiBaseUrl()}${scopedApiPath(path, scope)}`, {
    ...init, cache: "no-store", headers, signal: init.signal ?? AbortSignal.timeout(7000),
  });
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isUuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

export async function fetchScopedJson(path: string): Promise<unknown> {
  try {
    const response = await scopedSessionFetch(path, { signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new ApiUnavailableError();
    return await response.json() as unknown;
  } catch (error) {
    if (error instanceof ApiUnavailableError) throw error;
    throw new ApiUnavailableError();
  }
}
