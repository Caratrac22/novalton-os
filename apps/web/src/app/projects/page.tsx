import type { Metadata } from "next"; import { PlaceholderPage } from "@/components/placeholder-page";
export const metadata: Metadata = { title: "Projects" };
export default function ProjectsPage() { return <PlaceholderPage eyebrow="Workspace" title="Projects" description="Project workspaces will organize outcomes, status, tasks, and activity without becoming static folders." />; }
