export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function preview(value: string | null, maximum = 180): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maximum ? `${normalized.slice(0, maximum - 1)}…` : normalized;
}

export function humanize(value: string): string {
  const labels: Record<string, string> = {
    CREATED: "Créé", RUNNING: "En cours", COMPLETED: "Terminé", FAILED: "Échec",
    CANCELLED: "Annulé", PENDING: "En attente", READY: "Prêt", BLOCKED: "Bloqué",
    BACKLOG: "À faire", IN_PROGRESS: "En cours", REVIEW: "En revue", DONE: "Terminé",
    ACTIVE: "Actif", PAUSED: "En pause", ARCHIVED: "Archivé", SUCCEEDED: "Réussi",
    PASS: "Validé", PASS_WITH_WARNINGS: "Validé avec réserves", FAIL: "Échec",
    INCONCLUSIVE: "Non concluant", WAITING_FOR_HUMAN: "Décision humaine requise",
    ACCEPT_RESULT: "Accepter le résultat", REJECT_RESULT: "Rejeter le résultat",
    HUMAN_REVIEW_RECOMMENDED: "Examen humain recommandé", BLOCK_RECOMMENDED: "Blocage recommandé",
    BILLING_UNVERIFIED: "Facturation non vérifiée", REQUIRE_CONFIRMATION: "Confirmation requise",
  };
  return labels[value] ?? value.toLowerCase().replaceAll("_", " ").replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}
