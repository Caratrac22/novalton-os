import Link from "next/link";
export function ModulePlaceholder({ href, label, description }: Readonly<{ href: string; label: string; description: string }>) { return <Link className="module-card" href={href}><div><h3>{label}</h3><p>{description}</p></div><span className="module-link">Open placeholder <span aria-hidden="true">→</span></span></Link>; }
