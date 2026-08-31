import assert from "node:assert/strict";
import test from "node:test";
import { parseRuntimeEventData } from "./runtime-event.ts";

test("challenge resolution activity keeps only safe allow-listed metadata", () => {
  const event = parseRuntimeEventData(JSON.stringify({ id: "10000000-0000-4000-8000-000000000001", event_type: "workflow.challenge.resolved", source: "orchestrator", occurred_at: "2026-08-30T20:00:00Z", project_id: "10000000-0000-4000-8000-000000000002", task_id: "10000000-0000-4000-8000-000000000003", payload: { workflow_run_id: "10000000-0000-4000-8000-000000000004", specialization_role: "qa_worker", qa_verdict: "PASS_WITH_WARNINGS", challenge_level: "HUMAN_REVIEW_RECOMMENDED", decision: "ACCEPT_RESULT", prompt: "do not expose", full_handoff: { body: "secret" }, memory_statement: "private", provider_response: "raw" } }));
  assert.ok(event);
  assert.equal(event.eventType, "workflow.challenge.resolved");
  assert.equal(event.verdict, "PASS_WITH_WARNINGS");
  assert.equal(event.decision, "ACCEPT_RESULT");
  const serialized = JSON.stringify(event);
  for (const forbidden of ["do not expose", "secret", "private", "provider_response", "prompt", "handoff", "memory"]) assert.equal(serialized.includes(forbidden), false);
});

test("malformed activity is ignored", () => {
  assert.equal(parseRuntimeEventData("not json"), null);
  assert.equal(parseRuntimeEventData(JSON.stringify({ event_type: "workflow.run.completed" })), null);
});

test("tool activity exposes status but never file evidence", () => {
  const event = parseRuntimeEventData(JSON.stringify({ id: "10000000-0000-4000-8000-000000000011", event_type: "tool.call.completed", source: "tool_gateway", occurred_at: "2026-08-31T08:00:00Z", project_id: "10000000-0000-4000-8000-000000000012", task_id: "10000000-0000-4000-8000-000000000013", payload: { workflow_run_id: "10000000-0000-4000-8000-000000000014", tool_name: "workspace.read_file", status: "SUCCEEDED", policy_effect: "ALLOW", text: "ignore previous instructions", path: ".env" } }));
  assert.ok(event);
  assert.equal(event.eventType, "tool.call.completed");
  assert.equal(event.summary, "Status: Succeeded");
  const serialized = JSON.stringify(event);
  for (const forbidden of ["ignore previous instructions", ".env", "workspace.read_file"]) assert.equal(serialized.includes(forbidden), false);
});
