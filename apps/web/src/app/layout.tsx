import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Accueil · Novalton OS", template: "%s · Novalton OS" },
  description: "Novalton OS, projets et exécution gouvernée par agents IA.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body><a className="skip-link" href="#main-content">Aller au contenu</a><AppShell>{children}</AppShell></body></html>;
}
