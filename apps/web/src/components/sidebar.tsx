"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
const navigation = [{ href: "/", label: "Overview", icon: "home" }, { href: "/projects", label: "Projects", icon: "projects" }, { href: "/tasks", label: "Tasks", icon: "tasks" }, { href: "/activity", label: "Activity", icon: "activity" }] as const;
function NavIcon({ name }: Readonly<{ name: (typeof navigation)[number]["icon"] }>) {
  const paths = { home: <><path d="M3 10.5 12 3l9 7.5" /><path d="M5.5 9.5V21h13V9.5M9 21v-7h6v7" /></>, projects: <><path d="M3 7.5h7l2 2h9v10.5H3z" /><path d="M3 7.5V5h7l2 2" /></>, tasks: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="m3.5 6 1.25 1.25L7 4.75m-3.5 7.5 1.25 1.25L7 11m-3.5 7.25 1.25 1.25L7 17" /></>, activity: <path d="M3 12h4l2.5-7 5 14 2.5-7h4" /> };
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
export function Sidebar() {
  const pathname = usePathname();
  return <aside className="sidebar"><Link className="brand" href="/" aria-label="Novalton OS overview"><span className="brand-mark" aria-hidden="true">NO</span><span><span className="brand-name">Novalton OS</span><span className="brand-context">Command center</span></span></Link><nav className="primary-nav" aria-label="Primary navigation">{navigation.map((item) => { const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href); return <Link key={item.href} className="nav-link" href={item.href} aria-current={active ? "page" : undefined}><NavIcon name={item.icon} /><span>{item.label}</span></Link>; })}</nav><div className="sidebar-footer"><strong>Local operator</strong>Trusted workspace · governed execution</div></aside>;
}
