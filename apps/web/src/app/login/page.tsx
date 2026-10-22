import type { Metadata } from "next";
import Link from "next/link";
import { LocalLoginForm } from "@/components/local-login-form";

export const metadata: Metadata = { title: "Connexion" };

export default function LoginPage() {
  return <div className="page-stack"><section className="hero-panel"><p className="eyebrow">Compte Novalton</p>
    <h1>Se connecter</h1><p>Utilisez le compte initialisé par l’administrateur de cette instance.</p>
    <LocalLoginForm />
    {process.env.NOVALTON_OPERATOR_OIDC_ISSUER ? <Link href="/api/operator/auth/start">Utiliser le fournisseur OIDC configuré</Link> : null}
    </section></div>;
}
