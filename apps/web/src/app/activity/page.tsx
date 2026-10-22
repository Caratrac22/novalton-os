import type { Metadata } from "next";
import { ActivityFeed } from "@/components/activity-feed";
export const metadata: Metadata = { title: "Activité" };
export default function ActivityPage() { return <div className="page-stack"><section className="page-heading" aria-labelledby="activity-title"><p className="eyebrow">Observabilité</p><div><h1 id="activity-title">Activité</h1><p>Flux limité des événements d’exécution du workspace configuré, sans historique complet.</p></div></section><ActivityFeed /></div>; }
