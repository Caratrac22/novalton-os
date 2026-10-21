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
      setMessage(response.ok ? "Decision recorded." : "Decision denied or unavailable.");
      if (response.ok) router.refresh();
    } catch { setMessage("Decision unavailable."); } finally { setBusy(false); }
  }
  return <section aria-label="Operator decisions">
    <h2>Decisions</h2>
    {status !== "DONE" && status !== "CANCELLED" && <button type="button" disabled={busy} onClick={() => { if (window.confirm("Cancel this workflow?")) void act("cancel"); }}>Cancel workflow</button>}
    {status === "BLOCKED" && <form onSubmit={(event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      if (!window.confirm("Resolve using the fresh workflow and explicit budget?")) return;
      void act("resolve", {
        workflow_run_id: data.get("workflow_run_id"), request_key: data.get("request_key"),
        deadline: new Date(String(data.get("deadline"))).toISOString(), max_model_calls: Number(data.get("max_model_calls")),
      });
    }}>
      <p>A fresh, separately created workflow is required. This decision never replays the blocked attempt.</p>
      <label>Fresh workflow ID <input name="workflow_run_id" required /></label>
      <label>Unique request key <input name="request_key" required /></label>
      <label>Deadline (ISO timestamp) <input name="deadline" type="datetime-local" required /></label>
      <label>Model call limit <input name="max_model_calls" type="number" min="0" max="128" defaultValue="24" required /></label>
      <button type="submit" disabled={busy}>Resolve with fresh workflow</button>
    </form>}
    {message && <p role="status">{message}</p>}
  </section>;
}
