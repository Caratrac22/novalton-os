import "server-only";
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
export function getApiBaseUrl(): string {
  const configured = process.env.NOVALTON_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  let parsed: URL; try { parsed = new URL(configured); } catch { throw new Error("Invalid Novalton API configuration"); }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("Invalid Novalton API configuration");
  return parsed.toString().replace(/\/$/, "");
}
