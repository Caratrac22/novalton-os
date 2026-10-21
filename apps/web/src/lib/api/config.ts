import "server-only";
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_TENANT_ID = "89cfc055-366e-5bcb-b65f-4f367185bf6d";
const DEFAULT_WORKSPACE_ID = "b640b64f-8e55-53e8-a5b2-3beff9d5af82";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type WorkspaceScope = Readonly<{ tenantId: string; workspaceId: string }>;

export function getApiBaseUrl(): string {
  const configured = process.env.NOVALTON_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  let parsed: URL; try { parsed = new URL(configured); } catch { throw new Error("Invalid Novalton API configuration"); }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("Invalid Novalton API configuration");
  return parsed.toString().replace(/\/$/, "");
}

export function getWorkspaceScope(): WorkspaceScope {
  const tenantId = process.env.NOVALTON_TENANT_ID?.trim() || DEFAULT_TENANT_ID;
  const workspaceId = process.env.NOVALTON_WORKSPACE_ID?.trim() || DEFAULT_WORKSPACE_ID;
  if (!UUID_PATTERN.test(tenantId) || !UUID_PATTERN.test(workspaceId)) throw new Error("Invalid Novalton workspace configuration");
  return { tenantId, workspaceId };
}

export function operatorWorkspaceScopes(): WorkspaceScope[] {
  const fallback = getWorkspaceScope();
  const configured = process.env.NOVALTON_OPERATOR_WORKSPACE_SCOPES;
  if (!configured) return [fallback];
  const entries = configured.split(",");
  if (entries.length < 1 || entries.length > 10) throw new Error("Invalid operator workspace configuration");
  const scopes = entries.map((entry) => {
    const [tenantId, workspaceId, extra] = entry.trim().split(":");
    if (extra || !UUID_PATTERN.test(tenantId) || !UUID_PATTERN.test(workspaceId)) throw new Error("Invalid operator workspace configuration");
    return { tenantId, workspaceId };
  });
  if (new Set(scopes.map((scope) => scope.workspaceId)).size !== scopes.length) throw new Error("Duplicate operator workspace");
  return scopes;
}

export function selectedOperatorScope(workspaceId: string | undefined): WorkspaceScope {
  const scopes = operatorWorkspaceScopes();
  return scopes.find((scope) => scope.workspaceId === workspaceId) ?? scopes[0];
}

export function scopedApiPath(suffix: string, scope = getWorkspaceScope()): string {
  const { tenantId, workspaceId } = scope;
  const base = `/api/v1/tenants/${tenantId}/workspaces/${workspaceId}`;
  return suffix ? `${base}/${suffix.replace(/^\/+/, "")}` : base;
}
