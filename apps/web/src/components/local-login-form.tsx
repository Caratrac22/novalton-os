"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

export function LocalLoginForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const response = await fetch("/api/auth/local/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login: data.get("login"), password: data.get("password") }) });
      if (!response.ok) { setError((await response.json()).message ?? "Connexion impossible."); return; }
      form.reset(); router.push("/projects"); router.refresh();
    } catch { setError("Service de connexion indisponible."); }
    finally { setBusy(false); }
  }
  return <form className="workspace-form" onSubmit={submit}>
    <label htmlFor="login">Identifiant</label><input id="login" name="login" autoComplete="username" required maxLength={128} />
    <label htmlFor="password">Mot de passe</label><input id="password" name="password" type="password" autoComplete="current-password" required />
    <button disabled={busy} type="submit">{busy ? "Connexion…" : "Se connecter"}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}
