"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { primaryNavigation, sectionForPath, type NavigationIcon } from "@/lib/navigation";

function NavIcon({ name }: Readonly<{ name: NavigationIcon }>) {
  const paths = {
    home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V21h13V9.5M9 21v-7h6v7" /></>,
    projects: <><path d="M3 7.5h7l2 2h9v10.5H3z" /><path d="M3 7.5V5h7l2 2" /></>,
    control: <><path d="M3 12h4l2.5-7 5 14 2.5-7h4" /></>,
    environments: <><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><path d="M7 7.5h.01M7 16.5h.01" /></>,
    settings: <><path d="M12 3v3m0 12v3M3 12h3m12 0h3m-15.4-6.4 2.1 2.1m8.6 8.6 2.1 2.1m0-12.7-2.1 2.1m-8.6 8.6-2.1 2.1" /><circle cx="12" cy="12" r="4" /></>,
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Sidebar() {
  const pathname = usePathname();
  const selectedSection = sectionForPath(pathname);
  return <aside className="sidebar">
    <Link className="brand" href="/" aria-label="Novalton OS, accueil"><span className="brand-mark" aria-hidden="true">NO</span><span><span className="brand-name">Novalton OS</span><span className="brand-context">Espace de travail</span></span></Link>
    <nav className="primary-nav" aria-label="Navigation principale">{primaryNavigation.map((item) =>
      <Link key={item.href} className="nav-link" href={item.href} aria-current={selectedSection === item.href ? "page" : undefined}><NavIcon name={item.icon} /><span>{item.label}</span></Link>,
    )}</nav>
    <nav className="sidebar-shortcuts" aria-label="Accès directs"><span>Accès directs</span><Link href="/tasks">Tâches et missions</Link><Link href="/activity">Journal d’activité</Link><Link href="/operator">Console opérateur</Link></nav>
    <div className="sidebar-footer"><strong>Exécution gouvernée</strong>Les actions sensibles restent soumises aux autorisations du serveur.</div>
  </aside>;
}
