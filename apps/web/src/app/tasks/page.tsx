import type { Metadata } from "next"; import { PlaceholderPage } from "@/components/placeholder-page";
export const metadata: Metadata = { title: "Tasks" };
export default function TasksPage() { return <PlaceholderPage eyebrow="Execution" title="Tasks" description="Task planning and operational state will remain backed by the existing scoped API." />; }
