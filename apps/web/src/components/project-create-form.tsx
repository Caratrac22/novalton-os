"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function ProjectCreateForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), slug: slug.trim(), description: description.trim() || null }) });
      const value = await response.json() as { id?: string; message?: string };
      if (!response.ok || !value.id) throw new Error(value.message || "Impossible de créer le projet.");
      router.push(`/tasks?project=${value.id}`);
      router.refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Impossible de créer le projet."); }
    finally { setBusy(false); }
  }

  return <section className="entry-card" aria-labelledby="create-project-title"><div><p className="eyebrow">Création de projet</p><h2 id="create-project-title">Créer un projet</h2><p>Créez un projet dans l’espace configuré, puis accédez directement à ses tâches.</p></div><form className="entry-form" onSubmit={submit}><label>Nom<input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></label><label>Identifiant court<input required maxLength={63} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="operator-project" /></label><label className="entry-form-wide" >Description <span>(facultatif)</span><textarea maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>{error ? <p className="inline-error entry-form-wide" role="alert">{error}</p> : null}<button className="primary-button" disabled={busy}>{busy ? "Création en cours…" : "Créer un projet"}</button></form></section>;
}
