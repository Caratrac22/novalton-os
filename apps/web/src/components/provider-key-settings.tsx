"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";

type Entry = { provider: string; configured: boolean; enabled: boolean; key_available: boolean; chat_enabled: boolean };
const choices = [{ value: "openrouter", name: "OpenRouter" }, { value: "openai_compatible", name: "OpenAI compatible" }];

export function ProviderKeySettings() {
  const [items, setItems] = useState<Entry[]>([]);
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [passwords, setPasswords] = useState<Record<string, string>>({});
  const refresh = useCallback(async () => {
    const response = await fetch("/api/provider-keys", { cache: "no-store" });
    if (!response.ok) throw new Error("Configurations indisponibles ou connexion requise.");
    const data = await response.json() as { vault_available: boolean; items: Entry[] };
    setAvailable(data.vault_available); setItems(data.items);
  }, []);
  useEffect(() => { void Promise.resolve().then(refresh).catch((cause: Error) => setError(cause.message)); }, [refresh]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const provider = String(data.get("provider"));
    const secret = String(data.get("secret"));
    const current_password = String(data.get("password"));
    try {
      const response = await fetch(`/api/provider-keys/${provider}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret, current_password }) });
      if (!response.ok) throw new Error(response.status === 401 ? "Reconnectez-vous, puis vérifiez votre mot de passe." : "Enregistrement refusé. Vérifiez le coffre et vos droits.");
      form.reset(); setNotice("Clé enregistrée et désactivée. Aucun appel payant n’est autorisé."); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function change(provider: string, method: "PATCH" | "DELETE", enabled?: boolean) {
    const current_password = passwords[provider];
    if (!current_password) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/provider-keys/${provider}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password, ...(method === "PATCH" ? { enabled } : {}) }) });
      if (!response.ok) throw new Error(response.status === 401 ? "Reconnectez-vous, puis vérifiez votre mot de passe." : "Modification refusée.");
      setNotice(method === "DELETE" ? "Clé supprimée." : "État enregistré. Les appels distants restent interdits pour le chat."); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setPasswords((old) => ({ ...old, [provider]: "" })); setBusy(false); }
  }
  return <div className="workspace-form">
    <h3>Clés personnelles</h3>
    <p className="section-note">Le coffre est {available ? "disponible" : "non configuré sur le serveur"}. Enregistrer ou activer une clé n’autorise aucune dépense. Le chat utilise seulement le modèle local configuré.</p>
    <ul>{choices.map((choice) => { const entry = items.find((item) => item.provider === choice.value); return <li key={choice.value}>{choice.name} : {entry ? entry.key_available ? entry.enabled ? "configuré, actif pour une future autorisation" : "configuré, désactivé" : "clé du coffre indisponible" : "non configuré"} {entry && <><label htmlFor={`key-password-${choice.value}`}>Mot de passe Novalton pour {choice.name}</label><input id={`key-password-${choice.value}`} type="password" autoComplete="current-password" value={passwords[choice.value] ?? ""} onChange={(event) => setPasswords((old) => ({ ...old, [choice.value]: event.target.value }))} /><button type="button" disabled={busy || !entry.key_available || !passwords[choice.value]} onClick={() => void change(choice.value, "PATCH", !entry.enabled)}>{entry.enabled ? "Désactiver" : "Activer la configuration"}</button><button type="button" disabled={busy || !passwords[choice.value]} onClick={() => void change(choice.value, "DELETE")}>Supprimer la clé</button></>}</li>; })}</ul>
    <form className="workspace-form" onSubmit={submit} autoComplete="off">
      <label htmlFor="provider-choice">Fournisseur</label><select id="provider-choice" name="provider">{choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.name}</option>)}</select>
      <label htmlFor="provider-secret">Clé API</label><input id="provider-secret" name="secret" type="password" minLength={8} maxLength={4096} required autoComplete="off" />
      <label htmlFor="provider-password">Mot de passe Novalton actuel</label><input id="provider-password" name="password" type="password" required autoComplete="current-password" />
      <button disabled={busy || !available}>{busy ? "Enregistrement…" : "Enregistrer ou remplacer la clé"}</button>
    </form>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </div>;
}
