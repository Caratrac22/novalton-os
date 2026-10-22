import type { Metadata } from "next";
import Link from "next/link";
import { AppearanceControl } from "@/components/appearance-control";

export const metadata: Metadata = { title: "Paramètres" };

export default function SettingsPage() {
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="settings-title"><p className="eyebrow">Configuration</p><div><h1 id="settings-title">Paramètres</h1><p>Les réglages d’identité, les modèles et les intégrations sont encore administrés côté serveur. Cette page ne prétend pas modifier des permissions ou des secrets.</p></div></section>
    <div className="settings-grid">
      <section className="record-card"><h2>Apparence</h2><p className="settings-description">Préférence enregistrée sur cet appareil. Le mode clair utilise une palette verte.</p><AppearanceControl /></section>
      <section className="record-card"><h2>Identité opérateur</h2><p className="settings-description">La connexion et la sélection d’espace autorisé passent par le flux OIDC existant. Les actions sensibles restent vérifiées par le backend.</p><Link className="card-action" href="/operator">Ouvrir l’espace opérateur <span aria-hidden="true">→</span></Link></section>
      <section className="record-card"><h2>Modèles et budgets</h2><p className="settings-description">La sélection automatique des modèles et l’édition des budgets dans cette interface seront développées ultérieurement. Aucune dépense fournisseur n’est lancée ici.</p><span className="section-note">Interface de configuration à développer</span></section>
      <section className="record-card"><h2>Intégrations</h2><p className="settings-description">La gestion des connexions GitHub, Proxmox et autres services nécessitera des autorisations explicites et des contrôles serveur dédiés.</p><span className="section-note">Non configuré dans cette interface</span></section>
      <section className="record-card"><h2>Confidentialité et sécurité</h2><p className="settings-description">Aucun jeton, identifiant secret ni contenu brut des conversations d’agents n’est exposé dans ce tableau de bord.</p><Link className="card-action" href="/activity">Consulter le journal filtré <span aria-hidden="true">→</span></Link></section>
    </div>
  </div>;
}
