import type { Metadata } from "next";
import Link from "next/link";
import { SystemStatusCard } from "@/components/system-status-card";
import { getSystemStatus } from "@/lib/api/health";

export const metadata: Metadata = { title: "Environnements" };
export const dynamic = "force-dynamic";

export default async function EnvironmentsPage() {
  const status = await getSystemStatus();
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="env-title"><p className="eyebrow">Infrastructure</p><div><h1 id="env-title">Environnements</h1><p>État vérifiable des services internes. L’inventaire et le provisionnement de machines Proxmox, WSL2 ou Novalton Nodes ne sont pas encore disponibles.</p></div></section>
    <SystemStatusCard status={status} />
    <section className="state-panel" aria-labelledby="env-limits-title"><h2 id="env-limits-title">Gestion des environnements à venir</h2><p>Aucune VM, aucun nœud distant et aucune isolation d’exécution ne sont déclarés « actifs » sur cette page sans source d’inventaire autorisée. La vérification gouvernée I-044 demeure une fonctionnalité distincte de la gestion des machines.</p></section>
    <p className="secondary-navigation"><Link href="/control">Suivre les exécutions existantes <span aria-hidden="true">→</span></Link></p>
  </div>;
}
