import { StatusBadge, type StatusTone } from "@/components/status-badge";
import type { SystemStatus } from "@/lib/api/health";

function apiBadge(available: boolean): { label: string; tone: StatusTone } { return available ? { label: "Disponible", tone: "positive" } : { label: "Indisponible", tone: "negative" }; }
function dbBadge(status: SystemStatus["database"]): { label: string; tone: StatusTone } { if (status === "healthy") return { label: "Opérationnelle", tone: "positive" }; if (status === "unhealthy") return { label: "Indisponible", tone: "negative" }; return { label: "Inconnu", tone: "neutral" }; }

export function SystemStatusCard({ status }: Readonly<{ status: SystemStatus }>) {
  const api = apiBadge(status.api.available);
  const database = dbBadge(status.database);
  return <section className="status-card" aria-labelledby="system-status-title"><div className="status-card-header"><div><h2 id="system-status-title">État du système</h2><p>Contrôles de santé en direct, limités aux données publiables de l’API Novalton.</p></div><StatusBadge tone={api.tone}>{api.label}</StatusBadge></div><div className="status-grid"><div className="status-item"><span className="status-label">API</span><div className="status-value"><StatusBadge tone={api.tone}>{api.label}</StatusBadge></div><span className="status-meta">{status.api.available ? `${status.api.service} · v${status.api.version}` : "Le point de contrôle ne répond pas"}</span></div><div className="status-item"><span className="status-label">PostgreSQL</span><div className="status-value"><StatusBadge tone={database.tone}>{database.label}</StatusBadge></div><span className="status-meta">Stockage structuré côté serveur</span></div><div className="status-item"><span className="status-label">Environnement API</span><div className="status-value"><StatusBadge tone="neutral">{status.environment ?? "Inconnu"}</StatusBadge></div><span className="status-meta">Déclaré par le processus backend</span></div></div></section>;
}
