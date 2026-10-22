"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function TaskCreateForm({ projectId }: Readonly<{ projectId: string }>) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim(), description: description.trim() || null }) });
      const value = await response.json() as { id?: string; message?: string };
      if (!response.ok || !value.id) throw new Error(value.message || "Impossible de créer la tâche.");
      setTitle(""); setDescription("");
      router.push(`/tasks?project=${projectId}&task=${value.id}`);
      router.refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible de créer la tâche."); }
    finally { setBusy(false); }
  }

  return <section className="entry-card entry-card-compact" aria-labelledby="create-task-title"><div><p className="eyebrow">Objectif de la mission</p><h2 id="create-task-title">Créer une tâche</h2><p>La tâche est créée à l’état READY. Le lancement du workflow reste une action distincte.</p></div><form className="entry-form" onSubmit={submit}><label>Titre<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Décrivez l’objectif à réaliser" /></label><label className="entry-form-wide" >Contexte <span>(facultatif)</span><textarea maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>{error ? <p className="inline-error entry-form-wide" role="alert">{error}</p> : null}<button className="primary-button" disabled={busy}>{busy ? "Création en cours…" : "Créer une tâche"}</button></form></section>;
}
