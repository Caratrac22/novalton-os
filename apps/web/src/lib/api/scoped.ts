import "server-only";
import { getApiBaseUrl, scopedApiPath } from "@/lib/api/config";

export class ApiUnavailableError extends Error {
  constructor() { super("Workspace data is unavailable"); }
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
    const response = await fetch(`${getApiBaseUrl()}${scopedApiPath(path)}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) throw new ApiUnavailableError();
    return await response.json() as unknown;
  } catch (error) {
    if (error instanceof ApiUnavailableError) throw error;
    throw new ApiUnavailableError();
  }
}
