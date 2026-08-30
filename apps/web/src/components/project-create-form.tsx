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
      if (!response.ok || !value.id) throw new Error(value.message || "The project could not be created.");
      router.push(`/tasks?project=${value.id}`);
      router.refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The project could not be created."); }
    finally { setBusy(false); }
  }

  return <section className="entry-card" aria-labelledby="create-project-title"><div><p className="eyebrow">Operator entry</p><h2 id="create-project-title">Create project</h2><p>Create a workspace-scoped project, then continue directly to its tasks.</p></div><form className="entry-form" onSubmit={submit}><label>Name<input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></label><label>Slug<input required maxLength={63} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="operator-project" /></label><label className="entry-form-wide">Description <span>(optional)</span><textarea maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>{error ? <p className="inline-error entry-form-wide" role="alert">{error}</p> : null}<button className="primary-button" disabled={busy}>{busy ? "Creating project…" : "Create project"}</button></form></section>;
}
