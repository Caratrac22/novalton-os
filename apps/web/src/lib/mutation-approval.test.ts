import assert from "node:assert/strict";
import test from "node:test";
import { mutationApprovalState, mutationPreviewLabel } from "./mutation-approval.ts";
import type { OperatorToolCall } from "./api/workflow-types.ts";

const pending: OperatorToolCall = { id: "10000000-0000-4000-8000-000000000001", tool_name: "workspace.replace_text", status: "PENDING_APPROVAL", policy_effect: "REQUIRE_CONFIRMATION", approval_request_id: "10000000-0000-4000-8000-000000000002", execution_target_class: "LOCAL", duration_ms: null, result_count: null, bytes_returned: null, truncated: null, failure_code: null, target_path: "fixture.txt", mutation_fingerprint: "a".repeat(64), before_lines: 1, after_lines: 1, diff_preview: "-before\n+after\n", diff_truncated: false };

test("pending mutation exposes bounded preview and decision state", () => {
  assert.equal(mutationApprovalState(pending), "PENDING");
  assert.equal(mutationPreviewLabel(pending), "-before\n+after\n");
});

test("truncated and failed mutations cannot be approved", () => {
  assert.equal(mutationApprovalState({ ...pending, diff_truncated: true }), "TERMINAL");
  assert.equal(mutationPreviewLabel({ ...pending, diff_truncated: true }), "Preview exceeds the safe approval bound.");
  assert.equal(mutationPreviewLabel({ ...pending, failure_code: "stale_preimage" }), "Mutation unavailable: stale_preimage.");
});
