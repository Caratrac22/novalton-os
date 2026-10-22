import type { Metadata } from "next";
import Link from "next/link";
import { ActivityFeed } from "@/components/activity-feed";

export const metadata: Metadata = { title: "Centre de contrôle" };

export default function ControlPage() {
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="control-title"><p className="eyebrow">Supervision</p><div><h1 id="control-title">Centre de contrôle</h1><p>Consultez les événements d’exécution et accédez aux décisions de vos workflows sans contourner les approbations requises.</p></div></section>
    <section className="module-grid" aria-label="Actions de supervision">
      <Link className="module-card" href="/operator"><div><h3>Console opérateur</h3><p>Afficher les demandes durables, leur état et les actions autorisées pour la session authentifiée.</p></div><span className="module-link">Ouvrir la console <span aria-hidden="true">→</span></span></Link>
      <Link className="module-card" href="/tasks"><div><h3>Missions et workflows</h3><p>Sélectionner une tâche, consulter les étapes Manager, Developer et QA ainsi que leurs résultats.</p></div><span className="module-link">Voir les missions <span aria-hidden="true">→</span></span></Link>
      <Link className="module-card" href="/activity"><div><h3>Journal d’activité</h3><p>Consulter le flux de RuntimeEvents. Le flux ne remplace pas un historique complet après reconnexion.</p></div><span className="module-link">Ouvrir le journal <span aria-hidden="true">→</span></span></Link>
    </section>
    <ActivityFeed />
  </div>;
}
