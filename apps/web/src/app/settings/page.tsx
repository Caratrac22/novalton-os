import type { Metadata } from "next";
import Link from "next/link";
import { AppearanceControl } from "@/components/appearance-control";
import { LocalPasswordForm } from "@/components/local-password-form";
import { operatorWorkspaceScopes } from "@/lib/api/config";
import { scopedSessionFetch } from "@/lib/api/scoped";
import { cookies } from "next/headers";

export const metadata: Metadata = { title: "Paramètres" };

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const scopes = await Promise.all(operatorWorkspaceScopes().map(async (scope) =>
    (await scopedSessionFetch("projects?limit=1", {}, scope).catch(() => null))?.ok ? scope : null));
  const available = scopes.filter((scope) => scope !== null);
  const selected = (await cookies()).get("__Host-novalton-operator-workspace")?.value;
  const isLocal = (await cookies()).get("__Host-novalton-operator-session")?.value?.startsWith("nvl_") ?? false;
  const meResponse = await scopedSessionFetch("account/me").catch(() => null);
  const account = meResponse?.ok ? await meResponse.json() as { label?: string } : null;
  return <div className="page-stack">
    <section className="page-heading" aria-labelledby="settings-title"><p className="eyebrow">Configuration</p><div><h1 id="settings-title">Paramètres</h1><p>Les réglages d’identité, les modèles et les intégrations sont encore administrés côté serveur. Cette page ne prétend pas modifier des permissions ou des secrets.</p></div></section>
    <div className="settings-grid">
      <section className="record-card"><h2>Apparence</h2><p className="settings-description">Préférence enregistrée sur cet appareil. Le mode clair utilise une palette verte.</p><AppearanceControl /></section>
      <section className="record-card"><h2>Identité et espace</h2><p className="settings-description">Compte : {account?.label ?? "aucune session autorisée"}. Les droits sont vérifiés par le serveur.</p>{available.length ? <form className="workspace-form" action="/api/workspace" method="post"><label htmlFor="workspace-choice">Espace autorisé</label><select id="workspace-choice" name="workspace_id" defaultValue={available.some((scope) => scope.workspaceId === selected) ? selected : available[0].workspaceId}>{available.map((scope) => <option key={scope.workspaceId} value={scope.workspaceId}>{scope.workspaceId.slice(0, 8)} · {scope.tenantId.slice(0, 8)}</option>)}</select><button type="submit">Choisir cet espace</button></form> : <p className="section-note">Aucun espace accessible avec cette session.</p>}{isLocal && account ? <LocalPasswordForm /> : null}<Link className="card-action" href="/login">Connexion Novalton <span aria-hidden="true">→</span></Link>{account ? <form action="/api/auth/local/logout" method="post"><button type="submit">Se déconnecter</button></form> : null}<Link className="card-action" href="/operator">Ouvrir l’espace opérateur <span aria-hidden="true">→</span></Link></section>
      <section className="record-card"><h2>Modèles et budgets</h2><p className="settings-description">La sélection automatique des modèles et l’édition des budgets dans cette interface seront développées ultérieurement. Aucune dépense fournisseur n’est lancée ici.</p><span className="section-note">Interface de configuration à développer</span></section>
      <section className="record-card"><h2>Intégrations</h2><p className="settings-description">La gestion des connexions GitHub, Proxmox et autres services nécessitera des autorisations explicites et des contrôles serveur dédiés.</p><span className="section-note">Non configuré dans cette interface</span></section>
      <section className="record-card"><h2>Confidentialité et sécurité</h2><p className="settings-description">Aucun jeton, identifiant secret ni contenu brut des conversations d’agents n’est exposé dans ce tableau de bord.</p><Link className="card-action" href="/activity">Consulter le journal filtré <span aria-hidden="true">→</span></Link></section>
    </div>
  </div>;
}
