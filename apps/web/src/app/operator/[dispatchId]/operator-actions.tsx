"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function OperatorActions({ dispatchId, status }: { dispatchId: string; status: string }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function act(action: "cancel" | "resolve", body?: object) {
    setBusy(true);
    try {
      const response = await fetch(`/api/operator/${dispatchId}/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      setMessage(response.ok ? "Décision enregistrée." : "Décision refusée ou indisponible.");
      if (response.ok) router.refresh();
    } catch { setMessage("Décision indisponible."); } finally { setBusy(false); }
  }
  return <section aria-label="Décisions opérateur">
    <h2>Décisions</h2>
    {status !== "DONE" && status !== "CANCELLED" && <button type="button" disabled={busy} onClick={() => { if (window.confirm("Annuler cette exécution ?")) void act("cancel"); }}>Annuler l’exécution</button>}
    {status === "BLOCKED" && <form onSubmit={(event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const deadline = new Date(String(data.get("deadline")));
      if (Number.isNaN(deadline.getTime())) { setMessage("Échéance invalide."); return; }
      if (!window.confirm("Résoudre avec un nouveau workflow et une limite explicite d’appels modèle ?")) return;
      void act("resolve", {
        workflow_run_id: data.get("workflow_run_id"), request_key: data.get("request_key"),
        deadline: deadline.toISOString(), max_model_calls: Number(data.get("max_model_calls")),
      });
    }}>
      <p>Un nouveau workflow créé séparément est nécessaire. Cette décision ne rejoue jamais la tentative bloquée.</p>
      <label>Identifiant du nouveau workflow <input name="workflow_run_id" required /></label>
      <label>Clé de demande unique <input name="request_key" pattern="[a-zA-Z0-9_.:-]{1,128}" required /></label>
      <label>Échéance <input name="deadline" type="datetime-local" required /></label>
      <label>Nombre maximal d’appels modèle <input name="max_model_calls" type="number" min="0" max="128" defaultValue="24" required /></label>
      <button type="submit" disabled={busy}>Résoudre avec le nouveau workflow</button>
    </form>}
    {message && <p role="status">{message}</p>}
  </section>;
}
