"use client";
import { useState, type FormEvent } from "react";

export function LocalPasswordForm() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const response = await fetch("/api/auth/local/password", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current: data.get("current"), replacement: data.get("replacement") }) });
      if (!response.ok) { setMessage("Changement refusé. Vérifiez le mot de passe actuel et la session."); return; }
      form.reset(); setMessage("Mot de passe modifié. Toutes les sessions ont été révoquées. Reconnectez-vous.");
    } catch { setMessage("Service indisponible."); }
    finally { setBusy(false); }
  }
  return <form className="workspace-form" onSubmit={submit}>
    <label htmlFor="current-password">Mot de passe actuel</label><input id="current-password" name="current" type="password" autoComplete="current-password" required />
    <label htmlFor="new-password">Nouveau mot de passe (12 caractères minimum)</label><input id="new-password" name="replacement" type="password" autoComplete="new-password" minLength={12} required />
    <button type="submit" disabled={busy}>{busy ? "Enregistrement…" : "Changer le mot de passe"}</button>
    {message && <p role="status">{message}</p>}
  </form>;
}
