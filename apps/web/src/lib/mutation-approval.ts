import type { OperatorToolCall } from "@/lib/api/workflow-types";

export function mutationApprovalState(tool: OperatorToolCall): "PENDING" | "TERMINAL" | "UNAVAILABLE" {
  if (!tool.mutation_fingerprint) return "UNAVAILABLE";
  return tool.status === "PENDING_APPROVAL" && tool.approval_request_id && !tool.diff_truncated
    ? "PENDING"
    : "TERMINAL";
}

export function mutationPreviewLabel(tool: OperatorToolCall): string {
  if (tool.diff_truncated) return "Preview exceeds the safe approval bound.";
  if (tool.failure_code) return `Mutation unavailable: ${tool.failure_code}.`;
  return tool.diff_preview || "No bounded preview is available.";
}
