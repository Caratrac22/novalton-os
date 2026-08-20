import type { Metadata } from "next";
import { ActivityFeed } from "@/components/activity-feed";
export const metadata: Metadata = { title: "Activity" };
export default function ActivityPage() { return <div className="page-stack"><section className="page-heading" aria-labelledby="activity-title"><p className="eyebrow">Observability</p><div><h1 id="activity-title">Activity</h1><p>A live, bounded view of operational RuntimeEvents in the configured workspace.</p></div></section><ActivityFeed /></div>; }
