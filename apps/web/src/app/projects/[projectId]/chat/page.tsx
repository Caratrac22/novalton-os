import Link from "next/link";
import { getProject } from "@/lib/api/projects";
import { isUuid, scopedErrorMessage } from "@/lib/api/scoped";
import { ProjectChat } from "@/components/project-chat";

export const dynamic = "force-dynamic";
export default async function ChatPage({ params, searchParams }: {
  params: Promise<{ projectId: string }>; searchParams: Promise<{ conversation?: string }>;
}) {
  const { projectId } = await params;
  if (!isUuid(projectId)) return <section className="state-panel" role="alert">Projet invalide.</section>;
  let project;
  try { project = await getProject(projectId); }
  catch (error) { return <section className="state-panel" role="alert">{scopedErrorMessage(error)} <Link href="/projects">Voir les projets</Link></section>; }
  const initialConversation = (await searchParams).conversation;
  return <div className="page-stack">
    <section className="page-heading"><p className="eyebrow">Cadrage du projet</p><div>
      <h1>{project.name}</h1><p>Vos échanges sont enregistrés dans ce projet et accessibles uniquement avec vos droits.</p>
      <Link href={`/tasks?project=${projectId}`}>← Retour au projet</Link>
    </div></section>
    <ProjectChat projectId={projectId} initialConversation={initialConversation ?? ""} />
  </div>;
}
