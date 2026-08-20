import "server-only";
import { getApiBaseUrl } from "@/lib/api/config";
type Health = { service: string; version: string; environment: string };
export type SystemStatus = { api: ({ available: true } & Pick<Health, "service" | "version">) | { available: false }; database: "healthy" | "unhealthy" | "unknown"; environment: string | null };
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
function parseHealth(value: unknown): Health | null { return record(value) && value.status === "ok" && typeof value.service === "string" && typeof value.version === "string" && typeof value.environment === "string" ? { service: value.service, version: value.version, environment: value.environment } : null; }
function parseDatabase(value: unknown): SystemStatus["database"] { if (!record(value) || !record(value.dependencies) || !record(value.dependencies.postgres)) return "unknown"; const status = value.dependencies.postgres.status; return status === "healthy" || status === "unhealthy" ? status : "unknown"; }
async function fetchJson(path: string): Promise<unknown> { const response = await fetch(`${getApiBaseUrl()}${path}`, { cache: "no-store", signal: AbortSignal.timeout(3000) }); const value: unknown = await response.json(); if (!response.ok && response.status !== 503) throw new Error("Novalton API request failed"); return value; }
export async function getSystemStatus(): Promise<SystemStatus> {
  const [healthResult, databaseResult] = await Promise.allSettled([fetchJson("/api/v1/health"), fetchJson("/api/v1/health/dependencies")]);
  const health = healthResult.status === "fulfilled" ? parseHealth(healthResult.value) : null;
  return { api: health ? { available: true, service: health.service, version: health.version } : { available: false }, database: databaseResult.status === "fulfilled" ? parseDatabase(databaseResult.value) : "unknown", environment: health?.environment ?? null };
}
