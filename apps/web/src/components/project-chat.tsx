"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

type Conversation = { id: string; title: string; status: string };
type Message = { id: string; sequence: number; role: "USER" | "ASSISTANT"; content: string };
type Model = { local?: { model?: string | null; configured?: boolean }; external?: { configured?: boolean; chat_enabled?: boolean }; selection?: string };

export function ProjectChat({ projectId, initialConversation }: { projectId: string; initialConversation: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [moreConversations, setMoreConversations] = useState(false);
  const [active, setActive] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [after, setAfter] = useState(0);
  const [more, setMore] = useState(false);
  const [model, setModel] = useState<Model | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<{ content: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/conversations`;
  const loadMessages = useCallback(async (id: string, cursor = 0) => {
    const response = await fetch(`${base}/${id}/messages?after=${cursor}`, { cache: "no-store" });
    if (!response.ok) throw new Error(response.status === 403 ? "Accès refusé." : response.status === 404 ? "Conversation introuvable." : "Messages indisponibles.");
    const data = await response.json() as { items: Message[]; next_after: number };
    setMessages((old) => cursor === 0 ? data.items : [...new Map([...old, ...data.items].map((item) => [item.id, item])).values()].sort((a, b) => a.sequence - b.sequence));
    setAfter(data.next_after); setMore(data.items.length === 50);
  }, [base]);
  const selectConversation = useCallback(async (id: string) => {
    setError(""); setMessages([]);
    const response = await fetch(`${base}/${id}`, { cache: "no-store" });
    if (!response.ok) { setActive(null); throw new Error("Conversation introuvable ou accès révoqué."); }
    const chosen = await response.json() as Conversation;
    setActive(chosen); await loadMessages(id);
    window.history.replaceState(null, "", `/projects/${projectId}/chat?conversation=${id}`);
  }, [base, loadMessages, projectId]);
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetch(base, { cache: "no-store" }), fetch(`${base}/model`, { cache: "no-store" })])
      .then(async ([list, info]) => {
        if (!list.ok || !info.ok) throw new Error("Conversation indisponible. Vérifiez votre session et vos droits.");
        const payload = await list.json() as { items: Conversation[] };
        if (cancelled) return;
        setConversations(payload.items); setMoreConversations(payload.items.length === 50); setModel(await info.json() as Model);
        if (initialConversation) await selectConversation(initialConversation);
      }).catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : "Service indisponible."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [base, initialConversation, selectConversation]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const title = String(new FormData(form).get("title") ?? "").trim();
    try {
      const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
      if (!response.ok) throw new Error("Création refusée. Vérifiez vos droits sur le projet.");
      const item = await response.json() as Conversation;
      setConversations((old) => [item, ...old]); form.reset(); await selectConversation(item.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!active) return;
    setBusy(true); setError("");
    const form = event.currentTarget;
    const content = String(new FormData(form).get("content") ?? "").trim();
    if (!content) { setBusy(false); return; }
    try {
      const response = await fetch(`${base}/${active.id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, client_request_id: (pending.current?.content === content ? pending.current.id : (pending.current = { content, id: crypto.randomUUID() }).id) }) });
      if (!response.ok) throw new Error(response.status === 403 ? "Accès révoqué." : "Envoi refusé. Réessayez après vérification de la session.");
      const result = await response.json() as { assistant_status: string; message: Message; assistant?: Message | null };
      pending.current = null; form.reset();
      if (more || messages.length >= 50) {
        setMessages((old) => [...new Map([...old, result.message, ...(result.assistant ? [result.assistant] : [])].map((item) => [item.id, item])).values()].sort((a, b) => a.sequence - b.sequence));
      } else await loadMessages(active.id);
      if (result.assistant_status === "PROVIDER_ERROR") setError("Le modèle local a échoué. Votre message est enregistré.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Service indisponible."); }
    finally { setBusy(false); }
  }
  return <div className="chat-layout">
    <aside className="record-card chat-list"><h2>Conversations</h2>
      <form className="workspace-form" onSubmit={create}><label htmlFor="chat-title">Nouvel objectif</label><input id="chat-title" name="title" required maxLength={200} placeholder="Site vitrine pour mon entreprise" /><button disabled={busy}>Créer la conversation</button></form>
      {loading ? <p role="status">Chargement des conversations…</p> : conversations.length === 0 && !error ? <p>Aucune conversation pour ce projet.</p> : <ul>{conversations.map((item) => <li key={item.id}><button type="button" onClick={() => void selectConversation(item.id).catch((cause: Error) => setError(cause.message))} aria-current={active?.id === item.id ? "true" : undefined}>{item.title}</button></li>)}</ul>}
      {moreConversations && <button type="button" disabled={busy} onClick={() => void fetch(`${base}?offset=${conversations.length}`, { cache: "no-store" }).then(async (response) => { if (!response.ok) throw new Error("Liste indisponible."); const data = await response.json() as { items: Conversation[] }; setConversations((old) => [...old, ...data.items]); setMoreConversations(data.items.length === 50); }).catch(() => setError("Suite des conversations indisponible."))}>Plus de conversations</button>}
    </aside>
    <section className="record-card chat-thread" aria-label="Dialogue de cadrage"><h2>{active?.title ?? (loading ? "Chargement…" : "Choisissez une conversation")}</h2>
      <p className="section-note">{model?.local?.configured ? `Modèle local : ${model.local.model}` : "Aucun modèle local configuré. Vos messages sont enregistrés ; aucune réponse IA n’est générée."} {model?.external?.configured ? "Fournisseur externe configuré côté serveur, désactivé pour ce chat." : "Fournisseur externe non configuré."}</p>
      {messages.length === 0 && active ? <p>Aucun message. Décrivez votre objectif pour commencer.</p> : null}
      <ol className="chat-messages">{messages.map((item) => <li key={item.id} className={item.role === "USER" ? "chat-user" : "chat-assistant"}><strong>{item.role === "USER" ? "Vous" : "Assistant local"}</strong><p>{item.content}</p></li>)}</ol>
      {active && more && <button type="button" disabled={busy} onClick={() => void loadMessages(active.id, after).catch(() => setError("Suite des messages indisponible."))}>Afficher la suite</button>}
      {active && <form className="workspace-form" onSubmit={send}><label htmlFor="chat-content">Votre message</label><textarea id="chat-content" name="content" rows={4} maxLength={4000} required placeholder="Je voudrais créer…" /><button disabled={busy}>{busy ? "Envoi en cours…" : "Envoyer"}</button></form>}
      {active && <p className="section-note">Le dialogue ne lance aucun agent. Le cahier des charges et l’approbation ne sont pas encore disponibles.</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  </div>;
}
